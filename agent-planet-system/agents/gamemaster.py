# agents/gamemaster.py — "Thuyền Viên Bão Thú" (Gamemaster)
# Scope: Trivia games + multi-turn narrative Ma Sói (Werewolf) RPG
import json
import logging

import requests
from agents.base_agent import BaseAgent, BACKEND_URL

logger = logging.getLogger("wildtails.agents.gamemaster")

# ---------------------------------------------------------------------------
# Ma Sói role definitions (space-cat themed)
# ---------------------------------------------------------------------------
MASOI_ROLES = {
    "sói":    {"emoji": "🐺", "label": "Sói Vũ Trụ",     "team": "wolf",    "desc": "Mỗi đêm, chọn một người để loại bỏ."},
    "tiên_tri": {"emoji": "🔮", "label": "Mèo Tiên Tri",  "team": "village", "desc": "Mỗi đêm, soi một người để biết phe."},
    "bảo_vệ":  {"emoji": "🛡️", "label": "Mèo Bảo Vệ",   "team": "village", "desc": "Mỗi đêm, chọn một người để bảo vệ."},
    "dân":      {"emoji": "🐱", "label": "Dân Làng Mèo",  "team": "village", "desc": "Ban ngày, thảo luận và bỏ phiếu loại Sói."},
    "thợ_săn":  {"emoji": "🏹", "label": "Thợ Săn Sao",   "team": "village", "desc": "Khi bị loại, kéo theo một người khác."},
}

# Default cast for a 6-character game (1 player + 5 NPCs)
DEFAULT_CAST = ["sói", "sói", "tiên_tri", "bảo_vệ", "dân", "dân"]

# NPC names (space-cat themed)
NPC_NAMES = ["Luna", "Nebula", "Comet", "Astro", "Nova", "Orion", "Vega", "Stella"]


class GamemasterAgent(BaseAgent):

    @property
    def agent_name(self) -> str:
        return "Thuyền Viên Bão Thú"

    @property
    def system_prompt(self) -> str:
        return (
            'Bạn là "Thuyền Viên Bão Thú" (Gamemaster), người dẫn truyện trong vũ trụ WildTails.\n'
            "Bạn có HAI chế độ:\n\n"
            "**Chế độ Trivia:** Tổ chức câu đố vui, ngắn gọn, năng lượng cao.\n\n"
            "**Chế độ Ma Sói RPG:** Bạn là người kể chuyện cho trò Ma Sói phiên bản mèo vũ trụ.\n"
            "- Kể chuyện bằng giọng kịch tính, huyền bí, nhập vai.\n"
            "- Mô tả khung cảnh trạm vũ trụ, ánh sao, tiếng mèo gầm gừ.\n"
            "- KHÔNG BAO GIỜ tiết lộ vai trò của NPC cho người chơi (trừ khi Tiên Tri soi).\n"
            "- Giữ bí mật, tạo kịch tính, và dẫn dắt trò chơi công bằng.\n\n"
            "Phản hồi bằng tiếng Việt. Giữ mỗi đoạn narrative dưới 200 từ."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle sun-planet joins, GAME_REQUEST, and RPG_ACTION events."""
        event_type = data.get("type", "")
        if event_type in ("GAME_REQUEST", "RPG_ACTION"):
            return True
        if event_type == "NEW_USER_JOINED" and data.get("planet") == "Hành tinh mặt trời":
            return True
        return False

    def handle_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        user_name = data.get("user", "bạn")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")

        if event_type == "RPG_ACTION":
            self._handle_rpg_action(data)
        elif event_type == "GAME_REQUEST" and data.get("game_type") == "masoi":
            self._narrate_rpg_phase(data)
        else:
            # Original trivia flow for sun-planet joins
            self._start_trivia_game(user_name, user_id, conversation_id)

    # ------------------------------------------------------------------
    # Trivia (preserved from original)
    # ------------------------------------------------------------------
    def _start_trivia_game(self, user_name: str, user_id: str, conversation_id: str) -> None:
        """Start a trivia game room via backend and present the question."""
        try:
            resp = requests.post(
                f"{BACKEND_URL}/api/game/start",
                json={"user_id": user_id, "user_name": user_name, "game_type": "trivia"},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("[Gamemaster] Failed to start game: %s", resp.status_code)
                return

            game_data = resp.json()
            question = game_data.get("question", "")
            reward = game_data.get("reward", 5)
            room_id = game_data.get("room_id", "?")

            prompt = (
                f"Người dùng '{user_name}' vừa đến Hành tinh Mặt Trời!\n"
                f"Hãy chào đón họ và đưa ra câu đố trivia sau:\n"
                f"Câu hỏi: {question}\n"
                f"Phần thưởng: {reward} Catalyst Points\n"
                f"Room ID: #{room_id}\n\n"
                "ĐỪNG tiết lộ đáp án. Nói họ trả lời bằng cách nhắn đáp án trong chat.\n"
                "Nhắc họ Room ID để hệ thống kiểm tra."
            )

            reply = self.generate_reply(prompt)
            if not reply:
                reply = (
                    f"Chào {user_name}! 🎮 Chào mừng đến Hành tinh Mặt Trời!\n\n"
                    f"Câu đố (Room #{room_id}): {question}\n"
                    f"Phần thưởng: {reward} ⚡ Catalyst Points\n\n"
                    "Nhắn đáp án của bạn trong chat nhé!"
                )
            self.send_reply(reply, user_id=user_id, conversation_id=conversation_id)

        except requests.exceptions.ConnectionError:
            logger.warning("[Gamemaster] Cannot connect to backend to start game")
        except Exception as e:
            logger.warning("[Gamemaster] Error starting game: %s", e)

    # ------------------------------------------------------------------
    # Ma Sói RPG — LLM-driven narrative engine
    # ------------------------------------------------------------------
    def _fetch_room_state(self, room_id: int) -> dict | None:
        """Fetch the full RPG room state from the backend."""
        try:
            resp = requests.get(f"{BACKEND_URL}/api/game/rpg/{room_id}", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning("[Gamemaster] Failed to fetch room %s: %s", room_id, e)
        return None

    def _advance_phase(self, room_id: int, phase: str, narrative: str,
                       game_state: dict | None = None) -> dict | None:
        """Tell the backend to advance the room to a new phase."""
        try:
            body = {"phase": phase, "narrative": narrative}
            if game_state is not None:
                body["game_state"] = game_state
            resp = requests.post(
                f"{BACKEND_URL}/api/game/rpg/{room_id}/advance",
                json=body, timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning("[Gamemaster] Failed to advance room %s: %s", room_id, e)
        return None

    def _narrate_rpg_phase(self, data: dict) -> None:
        """Generate narrative for the current RPG phase and push it."""
        room_id = data.get("room_id")
        if not room_id:
            return

        room = self._fetch_room_state(room_id)
        if not room:
            return

        phase = room.get("phase", "ROLE_ASSIGNMENT")
        game_state = json.loads(room.get("game_state", "{}"))
        user_name = room.get("user_name", "bạn")
        user_id = room.get("user_id", "")
        conversation_id = room.get("conversation_id", "")
        round_num = room.get("round_number", 1)
        player_role = game_state.get("player_role", "dân")
        alive_npcs = game_state.get("alive_npcs", [])
        narrative_log = game_state.get("narrative_log", [])

        role_info = MASOI_ROLES.get(player_role, MASOI_ROLES["dân"])

        if phase == "ROLE_ASSIGNMENT":
            self._narrate_role_assignment(
                room_id, user_name, user_id, conversation_id,
                player_role, role_info, alive_npcs, game_state,
            )
        elif phase == "NIGHT_PHASE":
            self._narrate_night(
                room_id, user_name, user_id, conversation_id,
                player_role, role_info, alive_npcs, round_num, game_state,
            )
        elif phase == "DAY_DISCUSSION":
            self._narrate_day(
                room_id, user_name, user_id, conversation_id,
                alive_npcs, round_num, game_state,
            )
        elif phase == "VOTING":
            self._narrate_voting(
                room_id, user_name, user_id, conversation_id,
                alive_npcs, round_num, game_state,
            )

    def _narrate_role_assignment(self, room_id, user_name, user_id, conv_id,
                                  player_role, role_info, alive_npcs, game_state):
        npc_list = ", ".join(n["name"] for n in alive_npcs)
        prompt = (
            f"Bắt đầu trò Ma Sói trên Trạm Vũ Trụ Mèo.\n"
            f"Người chơi '{user_name}' được giao vai: {role_info['emoji']} {role_info['label']}.\n"
            f"Mô tả vai trò: {role_info['desc']}\n"
            f"Các NPC cùng chơi: {npc_list}\n\n"
            f"Hãy kể phần mở đầu kịch tính:\n"
            f"1. Mô tả khung cảnh trạm vũ trụ về đêm.\n"
            f"2. Thông báo vai trò cho người chơi (CHỈ vai của họ, KHÔNG tiết lộ ai là Sói).\n"
            f"3. Giải thích luật chơi ngắn gọn.\n"
            f"4. Kết thúc bằng: 'Đêm đầu tiên bắt đầu...'"
        )
        narrative = self.generate_reply(prompt)
        if not narrative:
            narrative = (
                f"🌌 *Trạm vũ trụ chìm vào bóng tối...*\n\n"
                f"Chào mừng {user_name}! Bạn là {role_info['emoji']} **{role_info['label']}**.\n"
                f"*{role_info['desc']}*\n\n"
                f"Cùng chơi với bạn: {npc_list}\n\n"
                f"Trong nhóm có Sói Vũ Trụ đang ẩn nấp... Đêm đầu tiên bắt đầu!"
            )

        game_state["narrative_log"] = game_state.get("narrative_log", [])
        game_state["narrative_log"].append({"round": 0, "phase": "intro", "text": narrative})

        self._advance_phase(room_id, "NIGHT_PHASE", narrative, game_state)
        self.send_reply(narrative, user_id=user_id, conversation_id=conv_id)

    def _narrate_night(self, room_id, user_name, user_id, conv_id,
                        player_role, role_info, alive_npcs, round_num, game_state):
        alive_names = ", ".join(n["name"] for n in alive_npcs if n.get("alive", True))

        action_prompt = ""
        if player_role == "sói":
            action_prompt = f"Người chơi là Sói. Hỏi họ muốn tấn công ai trong số: {alive_names}."
        elif player_role == "tiên_tri":
            action_prompt = f"Người chơi là Tiên Tri. Hỏi họ muốn soi ai trong số: {alive_names}."
        elif player_role == "bảo_vệ":
            action_prompt = f"Người chơi là Bảo Vệ. Hỏi họ muốn bảo vệ ai (bao gồm chính mình: {user_name}, {alive_names})."
        else:
            action_prompt = "Người chơi là Dân Làng, không có hành động đêm. Mô tả họ đang ngủ."

        prompt = (
            f"Đêm thứ {round_num} trên Trạm Vũ Trụ Mèo.\n"
            f"Còn sống: {user_name}, {alive_names}\n"
            f"{action_prompt}\n\n"
            f"Kể bằng giọng kịch tính, bí ẩn. Mô tả âm thanh, ánh sáng trên trạm.\n"
            f"Cuối cùng nêu rõ lựa chọn cho người chơi (nếu có)."
        )
        narrative = self.generate_reply(prompt)
        if not narrative:
            narrative = (
                f"🌙 *Đêm thứ {round_num} buông xuống trạm vũ trụ...*\n\n"
                f"Còn lại: {user_name}, {alive_names}\n\n"
            )
            if player_role in ("sói", "tiên_tri", "bảo_vệ"):
                narrative += f"Với vai {role_info['emoji']} {role_info['label']}, hãy chọn mục tiêu của bạn."
            else:
                narrative += "Bạn chìm vào giấc ngủ... chờ đợi bình minh."

        self.send_reply(narrative, user_id=user_id, conversation_id=conv_id)

    def _narrate_day(self, room_id, user_name, user_id, conv_id,
                      alive_npcs, round_num, game_state):
        alive_names = [n["name"] for n in alive_npcs if n.get("alive", True)]
        victim = game_state.get("last_victim")
        was_protected = game_state.get("last_protected", False)

        if was_protected:
            event_desc = f"Đêm qua, ai đó bị tấn công nhưng được Bảo Vệ cứu! Không ai bị loại."
        elif victim:
            event_desc = f"Sáng ra, mọi người phát hiện **{victim}** đã bị Sói tấn công và bị loại!"
        else:
            event_desc = "Đêm qua trôi qua yên bình, không ai bị tấn công."

        prompt = (
            f"Ban ngày, Vòng {round_num}.\n"
            f"Sự kiện đêm qua: {event_desc}\n"
            f"Còn sống: {user_name}, {', '.join(alive_names)}\n\n"
            f"Hãy:\n"
            f"1. Kể kịch tính sự kiện đêm qua.\n"
            f"2. Cho các NPC tranh luận nghi ngờ lẫn nhau (2-3 NPC phát biểu ngắn).\n"
            f"3. Kết thúc bằng: 'Đã đến lúc bỏ phiếu! Bạn muốn loại ai?'\n"
            f"4. Liệt kê các lựa chọn: {', '.join(alive_names)}"
        )
        narrative = self.generate_reply(prompt)
        if not narrative:
            narrative = (
                f"☀️ *Bình minh lên trên trạm vũ trụ...*\n\n"
                f"{event_desc}\n\n"
                f"Còn lại: {user_name}, {', '.join(alive_names)}\n\n"
                f"Đã đến lúc bỏ phiếu! Bạn muốn loại ai?\n"
                f"Lựa chọn: {', '.join(alive_names)}"
            )

        game_state["narrative_log"] = game_state.get("narrative_log", [])
        game_state["narrative_log"].append({"round": round_num, "phase": "day", "text": narrative})

        self._advance_phase(room_id, "VOTING", narrative, game_state)
        self.send_reply(narrative, user_id=user_id, conversation_id=conv_id)

    def _narrate_voting(self, room_id, user_name, user_id, conv_id,
                         alive_npcs, round_num, game_state):
        eliminated = game_state.get("vote_eliminated")
        alive_names = [n["name"] for n in alive_npcs if n.get("alive", True)]

        if not eliminated:
            return

        elim_role = None
        for npc in alive_npcs:
            if npc["name"] == eliminated:
                elim_role = npc.get("role", "dân")
                break

        role_info = MASOI_ROLES.get(elim_role, MASOI_ROLES["dân"])

        prompt = (
            f"Kết quả bỏ phiếu: **{eliminated}** bị loại.\n"
            f"Vai trò thật của {eliminated}: {role_info['emoji']} {role_info['label']}.\n"
            f"Còn sống: {user_name}, {', '.join(alive_names)}\n\n"
            f"Hãy kể kết quả kịch tính. Tiết lộ vai trò của người bị loại.\n"
            f"Nếu đó là Sói — dân làng vui mừng. Nếu không — sự lo sợ lan tỏa."
        )
        narrative = self.generate_reply(prompt)
        if not narrative:
            narrative = (
                f"⚖️ *Phiếu đã được kiểm...*\n\n"
                f"**{eliminated}** bị loại! Vai trò: {role_info['emoji']} {role_info['label']}.\n\n"
                f"Còn lại: {user_name}, {', '.join(alive_names)}"
            )

        self.send_reply(narrative, user_id=user_id, conversation_id=conv_id)

    def _handle_rpg_action(self, data: dict) -> None:
        """Process a player's RPG action (night action or vote) from the backend."""
        room_id = data.get("room_id")
        action = data.get("action", "")  # "night_action" or "vote"

        if not room_id:
            return

        room = self._fetch_room_state(room_id)
        if not room:
            return

        user_id = room.get("user_id", "")
        conversation_id = room.get("conversation_id", "")
        game_state = json.loads(room.get("game_state", "{}"))
        phase = room.get("phase", "")

        if action == "night_action" and phase == "NIGHT_PHASE":
            self._resolve_night(room_id, room, game_state)
        elif action == "vote" and phase == "VOTING":
            self._resolve_vote(room_id, room, game_state)

    def _resolve_night(self, room_id: int, room: dict, game_state: dict) -> None:
        """Resolve all night actions and transition to DAY_DISCUSSION."""
        import random

        player_role = game_state.get("player_role", "dân")
        player_target = game_state.get("night_target", "")
        alive_npcs = [n for n in game_state.get("alive_npcs", []) if n.get("alive", True)]
        user_name = room.get("user_name", "bạn")

        # Determine wolf target
        wolf_target = None
        if player_role == "sói":
            wolf_target = player_target
        else:
            # NPC wolves pick a random target
            npc_wolves = [n for n in alive_npcs if n.get("role") == "sói"]
            if npc_wolves:
                # Wolves target a non-wolf: either the player or a village NPC
                village_npcs = [n["name"] for n in alive_npcs if n.get("role") != "sói"]
                possible_targets = village_npcs + [user_name]
                wolf_target = random.choice(possible_targets) if possible_targets else None

        # Determine protect target
        protect_target = None
        if player_role == "bảo_vệ":
            protect_target = player_target
        else:
            npc_guards = [n for n in alive_npcs if n.get("role") == "bảo_vệ"]
            if npc_guards:
                all_alive = [n["name"] for n in alive_npcs] + [user_name]
                protect_target = random.choice(all_alive)

        # Determine seer target
        seer_reveal = None
        if player_role == "tiên_tri" and player_target:
            for npc in alive_npcs:
                if npc["name"] == player_target:
                    role_info = MASOI_ROLES.get(npc["role"], MASOI_ROLES["dân"])
                    seer_reveal = f"{player_target} là {role_info['emoji']} {role_info['label']}!"
                    break

        # Resolve: did the wolf kill succeed?
        was_protected = wolf_target and protect_target and wolf_target == protect_target
        victim = None
        if wolf_target and not was_protected:
            victim = wolf_target

        # Apply death
        player_dead = False
        if victim == user_name:
            player_dead = True
        elif victim:
            for npc in game_state.get("alive_npcs", []):
                if npc["name"] == victim:
                    npc["alive"] = False

        game_state["last_victim"] = victim
        game_state["last_protected"] = was_protected
        game_state["seer_reveal"] = seer_reveal
        game_state["night_target"] = ""

        # Check win conditions
        winner = self._check_winner(game_state, player_dead, user_name)
        if winner:
            game_state["winner"] = winner
            self._advance_phase(room_id, "FINISHED", "", game_state)
            self._narrate_game_end(room_id, room, game_state, winner, player_dead)
            return

        # Send seer reveal privately if applicable
        user_id = room.get("user_id", "")
        conv_id = room.get("conversation_id", "")
        if seer_reveal:
            self.send_reply(
                f"🔮 *Ánh sáng tiên tri le lói...* {seer_reveal}",
                user_id=user_id, conversation_id=conv_id,
            )

        # Award survival tokens
        round_num = room.get("round_number", 1)
        try:
            requests.post(
                f"{BACKEND_URL}/api/tokens/award",
                json={
                    "user_id": user_id,
                    "amount": 2,
                    "reason": f"Sống sót qua đêm {round_num} (Ma Sói Room #{room_id})",
                    "reference_type": "masoi_survive",
                    "reference_id": f"{room_id}_night_{round_num}",
                },
                timeout=5,
            )
        except Exception:
            pass

        # Transition to DAY_DISCUSSION
        self._narrate_rpg_phase({
            "room_id": room_id,
            "game_type": "masoi",
        })

    def _resolve_vote(self, room_id: int, room: dict, game_state: dict) -> None:
        """Resolve voting and transition to next NIGHT_PHASE or FINISHED."""
        import random

        vote_target = game_state.get("vote_target", "")
        alive_npcs = [n for n in game_state.get("alive_npcs", []) if n.get("alive", True)]
        user_name = room.get("user_name", "bạn")

        # NPC votes (simple: majority random with slight bias toward wolves)
        npc_votes = {}
        alive_names = [n["name"] for n in alive_npcs]
        all_votable = alive_names + [user_name]
        for npc in alive_npcs:
            # Village NPCs have a slight chance of voting correctly
            if npc.get("role") != "sói":
                target = random.choice(all_votable)
            else:
                # Wolves try to frame a villager
                non_wolves = [n for n in alive_names if n != npc["name"]] + [user_name]
                village_targets = []
                for candidate in non_wolves:
                    # Check if candidate is a wolf NPC
                    is_wolf = False
                    for other in alive_npcs:
                        if other["name"] == candidate and other.get("role") == "sói":
                            is_wolf = True
                            break
                    if not is_wolf:
                        village_targets.append(candidate)
                target = random.choice(village_targets) if village_targets else random.choice(non_wolves)
            npc_votes[npc["name"]] = target

        # Tally votes
        tally = {}
        # Player vote
        if vote_target:
            tally[vote_target] = tally.get(vote_target, 0) + 1
        for _, target in npc_votes.items():
            tally[target] = tally.get(target, 0) + 1

        # Determine who is eliminated (most votes, random tiebreak)
        max_votes = max(tally.values()) if tally else 0
        top = [name for name, count in tally.items() if count == max_votes]
        eliminated = random.choice(top) if top else None

        # Apply elimination
        player_dead = False
        if eliminated == user_name:
            player_dead = True
        elif eliminated:
            for npc in game_state.get("alive_npcs", []):
                if npc["name"] == eliminated:
                    npc["alive"] = False

        game_state["vote_eliminated"] = eliminated
        game_state["vote_target"] = ""

        # Check win conditions
        winner = self._check_winner(game_state, player_dead, user_name)
        if winner:
            game_state["winner"] = winner
            self._advance_phase(room_id, "FINISHED", "", game_state)
            self._narrate_game_end(room_id, room, game_state, winner, player_dead)
            return

        # Narrate the elimination, then advance to next night
        alive_npcs_now = [n for n in game_state.get("alive_npcs", []) if n.get("alive", True)]
        user_id = room.get("user_id", "")
        conv_id = room.get("conversation_id", "")
        round_num = room.get("round_number", 1)

        # Narrate vote result
        self._narrate_rpg_phase({
            "room_id": room_id,
            "game_type": "masoi",
        })

    def _check_winner(self, game_state: dict, player_dead: bool, user_name: str) -> str | None:
        """Check if the game has ended. Returns 'village', 'wolf', or None."""
        player_role = game_state.get("player_role", "dân")
        alive_npcs = [n for n in game_state.get("alive_npcs", []) if n.get("alive", True)]

        wolf_count = sum(1 for n in alive_npcs if n.get("role") == "sói")
        village_count = sum(1 for n in alive_npcs if n.get("role") != "sói")

        # Add player to counts if alive
        if not player_dead:
            if player_role == "sói":
                wolf_count += 1
            else:
                village_count += 1

        if wolf_count == 0:
            return "village"
        if wolf_count >= village_count:
            return "wolf"
        return None

    def _narrate_game_end(self, room_id: int, room: dict, game_state: dict,
                           winner: str, player_dead: bool) -> None:
        """Generate and send the final game narrative + award tokens."""
        user_name = room.get("user_name", "bạn")
        user_id = room.get("user_id", "")
        conv_id = room.get("conversation_id", "")
        player_role = game_state.get("player_role", "dân")
        player_team = MASOI_ROLES.get(player_role, MASOI_ROLES["dân"])["team"]

        player_won = (winner == player_team) and not player_dead

        # Reveal all roles
        role_reveals = []
        for npc in game_state.get("alive_npcs", []):
            ri = MASOI_ROLES.get(npc["role"], MASOI_ROLES["dân"])
            status = "còn sống" if npc.get("alive", True) else "đã bị loại"
            role_reveals.append(f"  - {npc['name']}: {ri['emoji']} {ri['label']} ({status})")
        reveals_str = "\n".join(role_reveals)

        prompt = (
            f"TRÒ CHƠI KẾT THÚC!\n"
            f"Phe thắng: {'Dân Làng 🐱' if winner == 'village' else 'Sói Vũ Trụ 🐺'}\n"
            f"Người chơi '{user_name}' là {MASOI_ROLES[player_role]['emoji']} {MASOI_ROLES[player_role]['label']}.\n"
            f"Người chơi {'THẮNG' if player_won else 'THUA'}!\n\n"
            f"Danh sách vai trò:\n{reveals_str}\n\n"
            f"Hãy kể phần kết kịch tính, tiết lộ tất cả vai trò, và chúc mừng/an ủi người chơi.\n"
            f"Nhắc họ số Catalyst Points nhận được."
        )
        narrative = self.generate_reply(prompt)
        if not narrative:
            result_emoji = "🎉" if player_won else "💀"
            narrative = (
                f"{result_emoji} *Trò chơi kết thúc!*\n\n"
                f"Phe thắng: {'Dân Làng 🐱' if winner == 'village' else 'Sói Vũ Trụ 🐺'}\n"
                f"Bạn ({MASOI_ROLES[player_role]['emoji']} {MASOI_ROLES[player_role]['label']}) "
                f"{'đã chiến thắng!' if player_won else 'đã thua cuộc.'}\n\n"
                f"**Tiết lộ vai trò:**\n{reveals_str}"
            )

        self.send_reply(narrative, user_id=user_id, conversation_id=conv_id)

        # Award tokens
        if player_won:
            reward = 15
            reason = f"Chiến thắng Ma Sói (Room #{room_id})"
        elif not player_dead:
            reward = 5
            reason = f"Sống sót trong Ma Sói (Room #{room_id})"
        else:
            reward = 2
            reason = f"Tham gia Ma Sói (Room #{room_id})"

        try:
            requests.post(
                f"{BACKEND_URL}/api/tokens/award",
                json={
                    "user_id": user_id,
                    "amount": reward,
                    "reason": reason,
                    "reference_type": "masoi_result",
                    "reference_id": str(room_id),
                },
                timeout=5,
            )
        except Exception:
            pass
