import asyncio
import json
import random
import os
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

LEADERBOARD_FILE = "leaderboard.json"

def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_leaderboard(data):
    with open(LEADERBOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class Settings(BaseModel):
    w_trash: float
    w_avoidfish: float
    w_avoidrobot: float

class ResetConfig(BaseModel):
    player_name: str
    mode: str # "solo" or "cpu"
    num_scouts: int
    num_collectors: int
    max_steps: int
    target_score: int
    max_battery: int
    charge_time: int
    fish_stress_limit: float

class Waypoint(BaseModel):
    x: float
    y: float

state = {
    "status": "standby",
    "mode": "solo",
    "step": 0,
    "max_steps": 120,
    "target_score": 2000,
    "max_battery": 200,
    "charge_time": 10,
    "fish_stress_limit": 10.0,
    "grid_width": 20.0,
    "grid_height": 20.0,
    "robots": [],
    "trash": [],
    "fishes": [],
    "settings": {"w_trash": 1.0, "w_avoidfish": 1.0, "w_avoidrobot": 1.0},
    "cpu_settings": {"w_trash": 1.0, "w_avoidfish": 1.0, "w_avoidrobot": 1.0},
    "shared_trash_memory": [],
    "cpu_shared_trash_memory": [],
    "scout_waypoints": [],
    "player_name": "Guest",
    "is_score_recorded": False, 
    "leaderboard": load_leaderboard(),
    "current_play_history": {}, 
    "current_ranking": [],      
    "accumulated_stress": 0.0,
    "stats": {"n_trash": 0, "n_collision": 0, "energy": 0, "total_stress": 0.0, "score": 0},
    "cpu_stats": {"n_trash": 0, "n_collision": 0, "energy": 0, "score": 0},
    "final_report": None
}

def calc_dist(a, b):
    return np.sqrt((a["x"] - b["x"])**2 + (a["y"] - b["y"])**2)

@app.post("/update_settings")
async def update_settings(settings: Settings):
    state["settings"]["w_trash"] = settings.w_trash
    state["settings"]["w_avoidfish"] = settings.w_avoidfish
    state["settings"]["w_avoidrobot"] = settings.w_avoidrobot
    return {"status": "success"}

@app.post("/add_waypoint")
async def add_waypoint(wp: Waypoint):
    state["scout_waypoints"].append({"x": wp.x, "y": wp.y})
    return {"status": "success"}

@app.post("/clear_leaderboard")
async def clear_leaderboard():
    empty_data = []
    save_leaderboard(empty_data)
    state["leaderboard"] = empty_data
    state["current_ranking"] = []
    state["final_report"] = None
    return {"status": "success"}

@app.post("/standby")
async def set_standby():
    state["status"] = "standby"
    return {"status": "success"}

# ✨ メタ学習アルゴリズム（歴代上位プレイヤーの構成と重みからCPUの強さを決定）
def get_cpu_params(leaderboard):
    valid = [e for e in leaderboard if "params" in e and e.get("final_score", 0) > 0]
    if not valid:
        return {"num_scouts": 2, "num_collectors": 5, "w_trash": 1.5, "w_avoidfish": 0.5, "w_avoidrobot": 1.0}
    
    valid.sort(key=lambda x: x["final_score"], reverse=True)
    top_half = valid[:max(1, len(valid)//2)]
    
    weights = [e["final_score"] for e in top_half]
    total_w = sum(weights)
    
    scouts = int(round(sum(e["params"]["num_scouts"] * w for e, w in zip(top_half, weights)) / total_w))
    cols = int(round(sum(e["params"]["num_collectors"] * w for e, w in zip(top_half, weights)) / total_w))
    wt = round(sum(e["params"]["w_trash"] * w for e, w in zip(top_half, weights)) / total_w, 1)
    waf = round(sum(e["params"]["w_avoidfish"] * w for e, w in zip(top_half, weights)) / total_w, 1)
    war = round(sum(e["params"]["w_avoidrobot"] * w for e, w in zip(top_half, weights)) / total_w, 1)
    
    while 200 * scouts + 300 * cols > 2000:
        if cols > 1: cols -= 1
        elif scouts > 1: scouts -= 1
        else: break
        
    return {"num_scouts": max(1, scouts), "num_collectors": max(1, cols), "w_trash": wt, "w_avoidfish": waf, "w_avoidrobot": war}

@app.post("/reset")
async def reset_simulation(config: ResetConfig):
    state["status"] = "running"
    state["mode"] = config.mode
    state["step"] = 0
    state["max_steps"] = config.max_steps
    state["target_score"] = config.target_score
    state["max_battery"] = config.max_battery
    state["charge_time"] = config.charge_time
    state["fish_stress_limit"] = config.fish_stress_limit
    state["player_name"] = config.player_name
    state["is_score_recorded"] = False
    state["accumulated_stress"] = 0.0
    state["stats"] = {"n_trash": 0, "n_collision": 0, "energy": 0, "total_stress": 0.0, "score": 0}
    state["cpu_stats"] = {"n_trash": 0, "n_collision": 0, "energy": 0, "score": 0}
    state["current_play_history"] = {}
    state["final_report"] = None
    
    state["leaderboard"] = load_leaderboard()
    
    final_ranking = []
    for entry in state["leaderboard"]:
        final_ranking.append({"name": entry["name"], "score": entry.get("final_score", 0)})
    state["current_ranking"] = sorted(final_ranking, key=lambda x: x["score"], reverse=True)
    
    state["trash"] = [{"x": random.uniform(0, 20), "y": random.uniform(0, 20)} for _ in range(10)]
    state["shared_trash_memory"] = []
    state["cpu_shared_trash_memory"] = []
    state["scout_waypoints"] = []
    
    state["fishes"] = [{"id": i, "x": random.uniform(0, 20), "y": random.uniform(0, 20), 
                        "vx": random.uniform(-0.5, 0.5), "vy": random.uniform(-0.5, 0.5), "stress": 0.0} for i in range(10)]
    
    robots = []
    r_id = 1
    
    for _ in range(config.num_scouts):
        robots.append({"id": r_id, "owner": "player", "type": "scout", "x": random.uniform(0, 20), "y": random.uniform(0, 20), "energy": config.max_battery, "is_charging": False, "charge_timer": 0, "target": None})
        r_id += 1
    for _ in range(config.num_collectors):
        robots.append({"id": r_id, "owner": "player", "type": "collector", "x": random.uniform(0, 20), "y": random.uniform(0, 20), "energy": config.max_battery, "is_charging": False, "charge_timer": 0, "target": None})
        r_id += 1

    if config.mode == "cpu":
        cpu_params = get_cpu_params(state["leaderboard"])
        state["cpu_settings"] = {"w_trash": cpu_params["w_trash"], "w_avoidfish": cpu_params["w_avoidfish"], "w_avoidrobot": cpu_params["w_avoidrobot"]}
        for _ in range(cpu_params["num_scouts"]):
            robots.append({"id": r_id, "owner": "cpu", "type": "scout", "x": random.uniform(0, 20), "y": random.uniform(0, 20), "energy": config.max_battery, "is_charging": False, "charge_timer": 0, "target": None})
            r_id += 1
        for _ in range(cpu_params["num_collectors"]):
            robots.append({"id": r_id, "owner": "cpu", "type": "collector", "x": random.uniform(0, 20), "y": random.uniform(0, 20), "energy": config.max_battery, "is_charging": False, "charge_timer": 0, "target": None})
            r_id += 1

    state["robots"] = robots
    return {"status": "success"}

def calculate_v_next(robot, assigned_target_list, all_robots):
    v_trash = np.array([0.0, 0.0])
    v_avoidfish = np.array([0.0, 0.0])
    v_avoidrobot = np.array([0.0, 0.0])
    
    owner = robot["owner"]
    my_settings = state["settings"] if owner == "player" else state["cpu_settings"]
    waypoints = state["scout_waypoints"] if owner == "player" else []

    if robot["type"] == "collector" and assigned_target_list:
        target = assigned_target_list[0]
        dx = target["x"] - robot["x"]
        dy = target["y"] - robot["y"]
        norm = np.linalg.norm([dx, dy])
        if norm > 0:
            v_trash = np.array([dx, dy]) / norm

    elif robot["type"] == "scout":
        if robot.get("target"):
            if calc_dist(robot, robot["target"]) < 0.5:
                robot["target"] = None

        if not robot.get("target") and waypoints:
            robot["target"] = waypoints.pop(0)

        v_target = np.array([0.0, 0.0])
        if robot.get("target"):
            dx = robot["target"]["x"] - robot["x"]
            dy = robot["target"]["y"] - robot["y"]
            norm = np.linalg.norm([dx, dy])
            if norm > 0:
                v_target = np.array([dx, dy]) / norm

        v_scout_repel = np.array([0.0, 0.0])
        for other in all_robots:
            if other["type"] == "scout" and other["id"] != robot["id"]:
                dist = calc_dist(robot, other)
                if dist <= 8.0 and dist > 0:
                    v_scout_repel += np.array([robot["x"] - other["x"], robot["y"] - other["y"]]) / dist

        if robot.get("target"):
            v_trash = v_target * 1.5 + v_scout_repel * 0.5
        else:
            v_trash = np.array([random.uniform(-0.5, 0.5), random.uniform(-0.5, 0.5)]) + v_scout_repel
            
        norm = np.linalg.norm(v_trash)
        if norm > 0:
            v_trash = v_trash / norm

    if state["fishes"]:
        min_dist_fish = float('inf')
        nearest_fish = None
        for f in state["fishes"]:
            dist = calc_dist(robot, f)
            if dist < min_dist_fish:
                min_dist_fish = dist
                nearest_fish = f
        if nearest_fish and min_dist_fish <= 3.0:
            dx = robot["x"] - nearest_fish["x"]
            dy = robot["y"] - nearest_fish["y"]
            norm = np.linalg.norm([dx, dy])
            if norm > 0:
                v_avoidfish = np.array([dx, dy]) / norm

    min_dist_robot = float('inf')
    nearest_other_robot = None
    for other in all_robots:
        if other["id"] != robot["id"]:
            dist = calc_dist(robot, other)
            if dist < min_dist_robot:
                min_dist_robot = dist
                nearest_other_robot = other
                
    if nearest_other_robot and min_dist_robot <= 2.0:
        dx = robot["x"] - nearest_other_robot["x"]
        dy = robot["y"] - nearest_other_robot["y"]
        norm = np.linalg.norm([dx, dy])
        if norm > 0:
            v_avoidrobot = np.array([dx, dy]) / norm
        else:
            v_avoidrobot = np.array([random.uniform(-1, 1), random.uniform(-1, 1)])

    v_noise = np.array([random.uniform(-0.1, 0.1), random.uniform(-0.1, 0.1)])

    w_trash = my_settings["w_trash"] if robot["type"] == "collector" else 1.0
    w_avoidfish = my_settings["w_avoidfish"]
    w_avoidrobot = my_settings["w_avoidrobot"]
    
    v_next = w_trash * v_trash + w_avoidfish * v_avoidfish + w_avoidrobot * v_avoidrobot + v_noise
    norm = np.linalg.norm(v_next)
    
    if norm > 0:
        v_next = (v_next / norm) * 1.0
        return float(v_next[0]), float(v_next[1])
    return 0.0, 0.0

async def simulation_loop():
    while True:
        if state["status"] == "running":
            state["step"] += 1
            
            num_new_trash = random.randint(0, 2)
            for _ in range(num_new_trash):
                state["trash"].append({
                    "x": random.uniform(0, 20),
                    "y": random.uniform(0, 20)
                })
                
            total_stress_current = 0.0
            surviving_fishes = []
            
            for fish in state["fishes"]:
                v_sep, v_ali, v_coh, v_avoid = np.zeros(2), np.zeros(2), np.zeros(2), np.zeros(2)
                neighbors = [f for f in state["fishes"] if f["id"] != fish["id"] and calc_dist(f, fish) < 3.0]
                
                if neighbors:
                    for n in neighbors:
                        d = calc_dist(fish, n)
                        if d > 0 and d < 1.0:
                            v_sep += np.array([fish["x"] - n["x"], fish["y"] - n["y"]]) / d
                        v_ali += np.array([n["vx"], n["vy"]])
                        v_coh += np.array([n["x"], n["y"]])
                    v_ali /= len(neighbors)
                    v_coh = (v_coh / len(neighbors)) - np.array([fish["x"], fish["y"]])
                
                robots_near = [r for r in state["robots"] if calc_dist(fish, r) < 3.0]
                for r in robots_near:
                    d = calc_dist(fish, r)
                    if d > 0:
                        v_avoid += np.array([fish["x"] - r["x"], fish["y"] - r["y"]]) / d

                trash_near = [t for t in state["trash"] if calc_dist(fish, t) < 1.0]
                
                if trash_near:
                    fish["stress"] += 1.0 
                elif robots_near:
                    fish["stress"] += 2.0 
                else:
                    fish["stress"] = max(0.0, fish["stress"] - 0.5)
                
                if fish["stress"] >= state.get("fish_stress_limit", 10.0):
                    state["accumulated_stress"] += fish["stress"]
                else:
                    v_new = np.array([fish["vx"], fish["vy"]]) + 0.5 * v_sep + 0.1 * v_ali + 0.05 * v_coh + 1.5 * v_avoid
                    speed = np.linalg.norm(v_new)
                    if speed > 1.0:
                        v_new = (v_new / speed) * 1.0
                    
                    fish["vx"], fish["vy"] = float(v_new[0]), float(v_new[1])
                    fish["x"] = (fish["x"] + fish["vx"]) % state["grid_width"]
                    fish["y"] = (fish["y"] + fish["vy"]) % state["grid_height"]
                    
                    surviving_fishes.append(fish)
                    total_stress_current += fish["stress"]
                
            state["fishes"] = surviving_fishes
            state["stats"]["total_stress"] = total_stress_current + state["accumulated_stress"]

            for robot in state["robots"]:
                if robot["type"] == "scout" and not robot.get("is_charging", False):
                    mem_key = "shared_trash_memory" if robot["owner"] == "player" else "cpu_shared_trash_memory"
                    new_discoveries = 0
                    memory_coords = {(tm["x"], tm["y"]) for tm in state[mem_key]}
                    
                    for t in state["trash"]:
                        if calc_dist(robot, t) <= 7.0:
                            if (t["x"], t["y"]) not in memory_coords:
                                state[mem_key].append(t.copy())
                                memory_coords.add((t["x"], t["y"]))
                                new_discoveries += 1
                    
                    if new_discoveries > 0:
                        consumed = 5 * new_discoveries
                        robot["energy"] -= consumed
                        if robot["owner"] == "player":
                            state["stats"]["energy"] += consumed
                        else:
                            state["cpu_stats"]["energy"] += consumed
                            
                        if robot["energy"] <= 0:
                            robot["is_charging"] = True
                            robot["charge_timer"] = 0

            claimed_player = set()
            claimed_cpu = set()
            collector_targets = {}
            active_collectors = [r for r in state["robots"] if r["type"] == "collector" and not r.get("is_charging", False)]

            for robot in active_collectors:
                owner = robot["owner"]
                mem_key = "shared_trash_memory" if owner == "player" else "cpu_shared_trash_memory"
                claimed_set = claimed_player if owner == "player" else claimed_cpu
                
                visible_trash = list(state[mem_key])
                memory_coords = {(t["x"], t["y"]) for t in visible_trash}
                
                for t in state["trash"]:
                    if calc_dist(robot, t) <= 2.0 and (t["x"], t["y"]) not in memory_coords:
                        visible_trash.append(t)

                min_dist = float('inf')
                best_trash = None
                for t in visible_trash:
                    t_coord = (t["x"], t["y"])
                    if t_coord in claimed_set:
                        continue
                    dist = calc_dist(robot, t)
                    if dist < min_dist:
                        min_dist = dist
                        best_trash = t

                if best_trash:
                    claimed_set.add((best_trash["x"], best_trash["y"]))
                    collector_targets[robot["id"]] = best_trash

            positions = []
            for robot in state["robots"]:
                owner = robot["owner"]
                stats_key = "stats" if owner == "player" else "cpu_stats"
                
                if robot.get("is_charging", False):
                    robot["charge_timer"] += 1
                    if robot["charge_timer"] >= state["charge_time"]:
                        robot["energy"] = state["max_battery"]
                        robot["is_charging"] = False
                        robot["charge_timer"] = 0
                    positions.append((robot["x"], robot["y"]))
                    continue

                assigned_target_list = []
                if robot["type"] == "collector":
                    target = collector_targets.get(robot["id"])
                    robot["target"] = target
                    if target:
                        assigned_target_list.append(target)

                dx, dy = calculate_v_next(robot, assigned_target_list, state["robots"])
                
                next_x = max(0.0, min(state["grid_width"] - 0.1, robot["x"] + dx))
                next_y = max(0.0, min(state["grid_height"] - 0.1, robot["y"] + dy))
                
                if abs(dx) > 0.01 or abs(dy) > 0.01:
                    robot["energy"] -= 1
                    state[stats_key]["energy"] += 1
                    
                robot["x"], robot["y"] = next_x, next_y

                for px, py in positions:
                    if np.sqrt((next_x - px)**2 + (next_y - py)**2) < 0.5:
                        state[stats_key]["n_collision"] += 1
                positions.append((next_x, next_y))

                if robot["type"] == "collector":
                    recovered = [t for t in state["trash"] if calc_dist(robot, t) < 1.0]
                    if recovered:
                        num_recovered = len(recovered)
                        state[stats_key]["n_trash"] += num_recovered
                        state["trash"] = [t for t in state["trash"] if t not in recovered]
                        state["shared_trash_memory"] = [t for t in state["shared_trash_memory"] if t not in recovered]
                        state["cpu_shared_trash_memory"] = [t for t in state["cpu_shared_trash_memory"] if t not in recovered]
                        robot["target"] = None
                        
                        consumed = 10 * num_recovered
                        robot["energy"] -= consumed
                        state[stats_key]["energy"] += consumed

                if robot["energy"] <= 0:
                    robot["is_charging"] = True
                    robot["charge_timer"] = 0

            while len(state["trash"]) < 5:
                state["trash"].append({
                    "x": random.uniform(0, 20),
                    "y": random.uniform(0, 20)
                })
            
            s_str = int(0.5 * state["stats"]["total_stress"])
            
            s_trash = 30 * state["stats"]["n_trash"]
            s_col = 10 * state["stats"]["n_collision"]
            s_ene = int(0.2 * state["stats"]["energy"])
            state["stats"]["score"] = int(s_trash - s_col - s_ene - s_str)

            c_trash = 30 * state["cpu_stats"]["n_trash"]
            c_col = 10 * state["cpu_stats"]["n_collision"]
            c_ene = int(0.2 * state["cpu_stats"]["energy"])
            state["cpu_stats"]["score"] = int(c_trash - c_col - c_ene - s_str)

            if state["mode"] == "solo" and state["step"] % 10 == 0 and state["step"] > 0 and state["step"] < state["max_steps"]:
                step_str = str(state["step"])
                state["current_play_history"][step_str] = state["stats"]["score"]
                
                ranking = []
                for entry in state["leaderboard"]:
                    if "history" in entry and step_str in entry["history"]:
                        ranking.append({"name": entry["name"], "score": entry["history"][step_str]})
                
                ranking.append({"name": state["player_name"] + " (あなた)", "score": state["stats"]["score"]})
                state["current_ranking"] = sorted(ranking, key=lambda x: x["score"], reverse=True)

            if state["step"] >= state["max_steps"]:
                state["status"] = "finished"
                if not state["is_score_recorded"]:
                    state["current_play_history"][str(state["max_steps"])] = state["stats"]["score"]
                    my_score = state["stats"]["score"]
                    
                    my_params = {
                        "num_scouts": len([r for r in state["robots"] if r["type"] == "scout" and r["owner"] == "player"]),
                        "num_collectors": len([r for r in state["robots"] if r["type"] == "collector" and r["owner"] == "player"]),
                        "w_trash": state["settings"]["w_trash"],
                        "w_avoidfish": state["settings"]["w_avoidfish"],
                        "w_avoidrobot": state["settings"]["w_avoidrobot"]
                    }

                    if state["mode"] == "solo":
                        state["leaderboard"].append({
                            "name": state["player_name"],
                            "final_score": my_score,
                            "history": dict(state["current_play_history"]),
                            "params": my_params
                        })
                        save_leaderboard(state["leaderboard"])
                        state["is_score_recorded"] = True
                        
                        final_ranking = []
                        all_scores = []
                        for entry in state["leaderboard"]:
                            score = int(entry.get("final_score", 0))
                            final_ranking.append({"name": entry["name"], "score": score})
                            all_scores.append(score)
                        
                        final_ranking_with_me = []
                        my_rank = 1
                        for rank in sorted(final_ranking, key=lambda x: x["score"], reverse=True):
                            if rank["name"] == state["player_name"] and rank["score"] == my_score and "(あなた)" not in rank["name"]:
                                final_ranking_with_me.append({"name": rank["name"] + " (あなた)", "score": rank["score"]})
                            else:
                                final_ranking_with_me.append(rank)
                            
                            if rank["score"] > my_score:
                                my_rank += 1
                                
                        state["current_ranking"] = sorted(final_ranking_with_me, key=lambda x: x["score"], reverse=True)

                        if len(all_scores) > 1:
                            avg = float(np.mean(all_scores))
                            std = float(np.std(all_scores))
                            dev = 50.0 if std == 0 else float(((my_score - avg) / std) * 10 + 50)
                        else:
                            dev = 50.0

                        state["final_report"] = {
                            "mode": "solo",
                            "name": state["player_name"],
                            "score": my_score,
                            "rank": my_rank,
                            "total_players": len(all_scores),
                            "deviation": round(dev, 1),
                            "num_scouts": my_params["num_scouts"],
                            "num_collectors": my_params["num_collectors"],
                            "w_trash": state["settings"]["w_trash"],
                            "w_avoidfish": state["settings"]["w_avoidfish"],
                            "w_avoidrobot": state["settings"]["w_avoidrobot"]
                        }
                    else:
                        state["is_score_recorded"] = True
                        cpu_score = state["cpu_stats"]["score"]
                        state["final_report"] = {
                            "mode": "cpu",
                            "name": state["player_name"],
                            "score": my_score,
                            "cpu_score": cpu_score,
                            "is_win": my_score >= cpu_score,
                            "num_scouts": my_params["num_scouts"],
                            "num_collectors": my_params["num_collectors"],
                            "w_trash": state["settings"]["w_trash"],
                            "w_avoidfish": state["settings"]["w_avoidfish"],
                            "w_avoidrobot": state["settings"]["w_avoidrobot"]
                        }

        await asyncio.sleep(0.5)

@app.on_event("startup")
async def startup_event():
    state["leaderboard"] = load_leaderboard()
    state["status"] = "standby"
    asyncio.create_task(simulation_loop())

@app.get("/")
async def get_html():
    return FileResponse("index.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps(state))
            await asyncio.sleep(0.5)
    except Exception:
        pass