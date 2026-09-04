#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KBO 매니저 - 컴투스 프로야구를 모티브로 한 텍스트 기반 야구 매니지먼트 게임
------------------------------------------------------------------
- 8개 가상 구단, 선수단(타자 13명 + 투수 11명) 자동 생성
- 확률 기반 타석 시뮬레이션 (컨택/파워/선구안/스피드 vs 구위/제구/체력)
- 주자 진루 로직, 불펜 운영, 선발 로테이션
- 시즌 일정 자동 생성, 순위표, 기록 리더보드(타율/홈런/평균자책점)
- 타순 변경, 선발 투수 지정
- 세이브 / 불러오기 (JSON)
"""

import random
import json
import os

SAVE_FILE = "kbo_manager_save.json"

# ============================================================
# 이름 생성
# ============================================================
LAST_NAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
              "한", "오", "서", "신", "권", "황", "안", "송", "유", "전"]
FIRST_NAMES = ["민준", "서준", "도윤", "예준", "시우", "주원", "하준", "지호", "준서", "건우",
               "현우", "도현", "지훈", "우진", "선우", "정우", "시윤", "연우", "유준", "승우",
               "재현", "동현", "성민", "태윤", "진호", "민재", "경수", "형준", "광호", "태양"]


def gen_name(used):
    for _ in range(50):
        name = random.choice(LAST_NAMES) + random.choice(FIRST_NAMES)
        if name not in used:
            used.add(name)
            return name
    name = random.choice(LAST_NAMES) + random.choice(FIRST_NAMES) + str(random.randint(1, 99))
    used.add(name)
    return name


TEAM_DATA = [
    ("서울 드래곤즈", "서울"),
    ("부산 파이어버드", "부산"),
    ("대구 타이탄스", "대구"),
    ("인천 유니콘스", "인천"),
    ("광주 라이온하트", "광주"),
    ("대전 헌터스", "대전"),
    ("수원 팰컨스", "수원"),
    ("창원 스핀드래곤", "창원"),
]

POSITIONS = ["포수", "1루수", "2루수", "3루수", "유격수", "좌익수", "중견수", "우익수", "지명타자"]


def clamp(v, lo=1, hi=99):
    return max(lo, min(hi, v))


def fmt3(x):
    """0.323 -> '.323' 야구식 표기"""
    s = f"{x:.3f}"
    if s.startswith("0."):
        return s[1:]
    if s.startswith("-0."):
        return "-" + s[2:]
    return s


# ============================================================
# 선수 클래스
# ============================================================
class Batter:
    def __init__(self, name, position):
        self.name = name
        self.position = position
        self.contact = clamp(random.randint(40, 90))
        self.power = clamp(random.randint(30, 90))
        self.eye = clamp(random.randint(30, 90))
        self.speed = clamp(random.randint(30, 90))
        self.defense = clamp(random.randint(40, 90))
        self.reset_season()

    def reset_season(self):
        self.pa = 0
        self.ab = 0
        self.hits = 0
        self.doubles = 0
        self.triples = 0
        self.hr = 0
        self.rbi = 0
        self.bb = 0
        self.so = 0
        self.runs = 0

    @property
    def avg(self):
        return round(self.hits / self.ab, 3) if self.ab > 0 else 0.0

    @property
    def obp(self):
        denom = self.ab + self.bb
        return round((self.hits + self.bb) / denom, 3) if denom > 0 else 0.0

    @property
    def slg(self):
        if self.ab == 0:
            return 0.0
        singles = self.hits - self.doubles - self.triples - self.hr
        tb = singles + self.doubles * 2 + self.triples * 3 + self.hr * 4
        return round(tb / self.ab, 3)

    def overall(self):
        return round((self.contact + self.power + self.eye + self.speed) / 4, 1)

    def to_dict(self):
        return self.__dict__.copy()

    @staticmethod
    def from_dict(d):
        b = Batter.__new__(Batter)
        b.__dict__.update(d)
        return b


class Pitcher:
    def __init__(self, name, role):
        self.name = name
        self.role = role  # "선발" / "중간" / "마무리"
        self.stuff = clamp(random.randint(40, 90))
        self.control = clamp(random.randint(40, 90))
        self.stamina = clamp(random.randint(30, 95)) if role == "선발" else clamp(random.randint(20, 60))
        self.reset_season()

    def reset_season(self):
        self.games = 0
        self.wins = 0
        self.losses = 0
        self.saves = 0
        self.outs = 0
        self.earned_runs = 0
        self.strikeouts = 0
        self.walks = 0
        self.hits_allowed = 0

    @property
    def innings(self):
        return self.outs // 3 + (self.outs % 3) / 3

    @property
    def era(self):
        ip = self.innings
        return round((self.earned_runs * 9 / ip), 2) if ip > 0 else 0.0

    def overall(self):
        return round((self.stuff + self.control) / 2, 1)

    def to_dict(self):
        return self.__dict__.copy()

    @staticmethod
    def from_dict(d):
        p = Pitcher.__new__(Pitcher)
        p.__dict__.update(d)
        return p


class Team:
    def __init__(self, name, city):
        self.name = name
        self.city = city
        self.lineup = []
        self.bench = []
        self.rotation = []
        self.bullpen = []
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.runs_scored = 0
        self.runs_allowed = 0
        self.rotation_idx = 0
        self.forced_starter_idx = None

    @property
    def games(self):
        return self.wins + self.losses + self.draws

    @property
    def win_pct(self):
        return round(self.wins / self.games, 3) if self.games > 0 else 0.0

    def all_batters(self):
        return self.lineup + self.bench

    def all_pitchers(self):
        return self.rotation + self.bullpen

    def to_dict(self):
        return {
            "name": self.name, "city": self.city,
            "lineup": [b.to_dict() for b in self.lineup],
            "bench": [b.to_dict() for b in self.bench],
            "rotation": [p.to_dict() for p in self.rotation],
            "bullpen": [p.to_dict() for p in self.bullpen],
            "wins": self.wins, "losses": self.losses, "draws": self.draws,
            "runs_scored": self.runs_scored, "runs_allowed": self.runs_allowed,
            "rotation_idx": self.rotation_idx,
        }

    @staticmethod
    def from_dict(d):
        t = Team(d["name"], d["city"])
        t.lineup = [Batter.from_dict(x) for x in d["lineup"]]
        t.bench = [Batter.from_dict(x) for x in d["bench"]]
        t.rotation = [Pitcher.from_dict(x) for x in d["rotation"]]
        t.bullpen = [Pitcher.from_dict(x) for x in d["bullpen"]]
        t.wins = d["wins"]; t.losses = d["losses"]; t.draws = d["draws"]
        t.runs_scored = d["runs_scored"]; t.runs_allowed = d["runs_allowed"]
        t.rotation_idx = d.get("rotation_idx", 0)
        return t


def create_team(name, city, used_names):
    team = Team(name, city)
    for pos in POSITIONS:
        team.lineup.append(Batter(gen_name(used_names), pos))
    for _ in range(4):
        team.bench.append(Batter(gen_name(used_names), random.choice(POSITIONS)))
    for _ in range(5):
        team.rotation.append(Pitcher(gen_name(used_names), "선발"))
    for i in range(6):
        role = "마무리" if i == 0 else "중간"
        team.bullpen.append(Pitcher(gen_name(used_names), role))
    return team


def create_league():
    used = set()
    return [create_team(n, c, used) for n, c in TEAM_DATA]


def generate_schedule(num_teams, games_per_matchup=8):
    schedule = []
    for i in range(num_teams):
        for j in range(i + 1, num_teams):
            half = games_per_matchup // 2
            for _ in range(half):
                schedule.append((i, j))
                schedule.append((j, i))
    random.shuffle(schedule)
    return schedule


# ============================================================
# 시뮬레이션 엔진
# ============================================================
def simulate_at_bat(batter, pitcher):
    contact_diff = batter.contact - pitcher.control
    power_diff = batter.power - pitcher.stuff

    bb_chance = clamp(8 + (batter.eye - pitcher.control) * 0.15, 3, 20) / 100
    k_chance = clamp(20 + (pitcher.stuff - batter.contact) * 0.22, 8, 38) / 100

    if random.random() < bb_chance:
        return "BB"
    if random.random() < k_chance:
        return "K"

    hit_chance = clamp(33 + contact_diff * 0.32, 20, 48) / 100
    if random.random() < hit_chance:
        hr_chance = clamp(7 + power_diff * 0.3, 1, 20)
        triple_chance = clamp(1 + (batter.speed - 50) * 0.05, 0.2, 5)
        double_chance = clamp(16 + power_diff * 0.15, 8, 30)
        r = random.uniform(0, 100)
        if r < hr_chance:
            return "HR"
        elif r < hr_chance + double_chance:
            return "2B"
        elif r < hr_chance + double_chance + triple_chance:
            return "3B"
        else:
            return "1B"
    return "OUT"


def walk_advance(bases, batter):
    runs = 0
    if bases[0] is not None:
        if bases[1] is not None:
            if bases[2] is not None:
                bases[2].runs += 1
                runs += 1
            bases[2] = bases[1]
        bases[1] = bases[0]
    bases[0] = batter
    return runs


def hit_advance(bases, batter, hit_type):
    runs = 0
    new_bases = [None, None, None]
    if hit_type == "1B":
        if bases[2] is not None:
            bases[2].runs += 1; runs += 1
        if bases[1] is not None:
            if random.random() < 0.6:
                bases[1].runs += 1; runs += 1
            else:
                new_bases[2] = bases[1]
        if bases[0] is not None:
            if random.random() < 0.25 and new_bases[2] is None:
                new_bases[2] = bases[0]
            else:
                new_bases[1] = bases[0]
        new_bases[0] = batter
    elif hit_type == "2B":
        if bases[2] is not None:
            bases[2].runs += 1; runs += 1
        if bases[1] is not None:
            bases[1].runs += 1; runs += 1
        if bases[0] is not None:
            if random.random() < 0.45:
                bases[0].runs += 1; runs += 1
            else:
                new_bases[2] = bases[0]
        new_bases[1] = batter
    elif hit_type == "3B":
        for r_ in bases:
            if r_ is not None:
                r_.runs += 1; runs += 1
        new_bases[2] = batter
    elif hit_type == "HR":
        for r_ in bases:
            if r_ is not None:
                r_.runs += 1; runs += 1
        batter.runs += 1
        runs += 1
        new_bases = [None, None, None]
    return runs, new_bases


def simulate_half_inning(team, pitcher, start_idx, hits_counter):
    outs = 0
    bases = [None, None, None]
    runs = 0
    idx = start_idx
    while outs < 3:
        batter = team.lineup[idx % 9]
        idx += 1
        batter.pa += 1
        result = simulate_at_bat(batter, pitcher)
        if result == "BB":
            batter.bb += 1
            pitcher.walks += 1
            scored = walk_advance(bases, batter)
            runs += scored
            batter.rbi += scored
        elif result == "K":
            batter.ab += 1
            batter.so += 1
            pitcher.strikeouts += 1
            pitcher.outs += 1
            outs += 1
        elif result == "OUT":
            batter.ab += 1
            pitcher.outs += 1
            outs += 1
        else:
            batter.ab += 1
            batter.hits += 1
            pitcher.hits_allowed += 1
            hits_counter[0] += 1
            if result == "2B":
                batter.doubles += 1
            elif result == "3B":
                batter.triples += 1
            elif result == "HR":
                batter.hr += 1
            scored, bases = hit_advance(bases, batter, result)
            runs += scored
            batter.rbi += scored
    return runs, idx


def pick_reliever(team, need_closer=False):
    closers = [p for p in team.bullpen if p.role == "마무리"]
    middles = [p for p in team.bullpen if p.role != "마무리"]
    if need_closer and closers:
        return closers[0]
    if middles:
        return random.choice(middles)
    if team.bullpen:
        return random.choice(team.bullpen)
    return team.rotation[0]


def simulate_game(home, away):
    home_score = 0
    away_score = 0
    home_idx = 0
    away_idx = 0
    home_hits = [0]
    away_hits = [0]
    line_home = []
    line_away = []

    if home.forced_starter_idx is not None:
        home_pitcher = home.rotation[home.forced_starter_idx]
        home.forced_starter_idx = None
    else:
        home_pitcher = home.rotation[home.rotation_idx % len(home.rotation)]
        home.rotation_idx += 1

    if away.forced_starter_idx is not None:
        away_pitcher = away.rotation[away.forced_starter_idx]
        away.forced_starter_idx = None
    else:
        away_pitcher = away.rotation[away.rotation_idx % len(away.rotation)]
        away.rotation_idx += 1

    home_pitcher.games += 1
    away_pitcher.games += 1
    home_game_outs = 0
    away_game_outs = 0

    win_pitcher_home = None
    win_pitcher_away = None
    lose_pitcher_home = None
    lose_pitcher_away = None

    def start_limit(p):
        return int(15 + p.stamina * 0.15)

    inning = 1
    while True:
        pre_away_score = away_score
        runs, away_idx = simulate_half_inning(away, home_pitcher, away_idx, home_hits)
        away_score += runs
        home_pitcher.earned_runs += runs
        line_away.append(away_score - pre_away_score)
        if away_score > home_score and pre_away_score <= home_score:
            win_pitcher_away = away_pitcher
            lose_pitcher_home = home_pitcher
        home_game_outs += 3
        if home_game_outs >= start_limit(home_pitcher) and home.bullpen:
            need_closer = inning >= 9 and 0 < (home_score - away_score) <= 3
            home_pitcher = pick_reliever(home, need_closer)
            home_pitcher.games += 1
            home_game_outs = 0

        if inning >= 9 and home_score > away_score:
            line_home.append(0)
            break

        pre_home_score = home_score
        runs, home_idx = simulate_half_inning(home, away_pitcher, home_idx, away_hits)
        home_score += runs
        away_pitcher.earned_runs += runs
        line_home.append(home_score - pre_home_score)
        if home_score > away_score and pre_home_score <= away_score:
            win_pitcher_home = home_pitcher
            lose_pitcher_away = away_pitcher
        away_game_outs += 3
        if away_game_outs >= start_limit(away_pitcher) and away.bullpen:
            need_closer = inning >= 9 and 0 < (away_score - home_score) <= 3
            away_pitcher = pick_reliever(away, need_closer)
            away_pitcher.games += 1
            away_game_outs = 0

        if inning >= 9 and home_score != away_score:
            break
        if inning >= 12 and home_score == away_score:
            break
        inning += 1

    if home_score > away_score:
        home.wins += 1
        away.losses += 1
        wp = win_pitcher_home or home_pitcher
        lp = lose_pitcher_away or away_pitcher
        wp.wins += 1
        lp.losses += 1
        if home_pitcher is not wp and home_pitcher.role == "마무리" and 0 < home_score - away_score <= 3:
            home_pitcher.saves += 1
    elif away_score > home_score:
        away.wins += 1
        home.losses += 1
        wp = win_pitcher_away or away_pitcher
        lp = lose_pitcher_home or home_pitcher
        wp.wins += 1
        lp.losses += 1
        if away_pitcher is not wp and away_pitcher.role == "마무리" and 0 < away_score - home_score <= 3:
            away_pitcher.saves += 1
    else:
        home.draws += 1
        away.draws += 1

    home.runs_scored += home_score
    home.runs_allowed += away_score
    away.runs_scored += away_score
    away.runs_allowed += home_score

    return {
        "home_score": home_score, "away_score": away_score,
        "line_home": line_home, "line_away": line_away,
        "home_hits": home_hits[0], "away_hits": away_hits[0],
        "home_pitcher": home_pitcher.name, "away_pitcher": away_pitcher.name,
    }


# ============================================================
# 게임 상태 / 저장·불러오기
# ============================================================
class GameState:
    def __init__(self):
        self.teams = create_league()
        self.schedule = generate_schedule(len(self.teams))
        self.game_idx = 0
        self.user_team_idx = None
        self.season_num = 1

    def to_dict(self):
        return {
            "teams": [t.to_dict() for t in self.teams],
            "schedule": self.schedule,
            "game_idx": self.game_idx,
            "user_team_idx": self.user_team_idx,
            "season_num": self.season_num,
        }

    @staticmethod
    def from_dict(d):
        gs = GameState.__new__(GameState)
        gs.teams = [Team.from_dict(t) for t in d["teams"]]
        gs.schedule = [tuple(x) for x in d["schedule"]]
        gs.game_idx = d["game_idx"]
        gs.user_team_idx = d["user_team_idx"]
        gs.season_num = d["season_num"]
        return gs

    def save(self, path=SAVE_FILE):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @staticmethod
    def load(path=SAVE_FILE):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return GameState.from_dict(d)

    def new_season(self):
        for t in self.teams:
            t.wins = t.losses = t.draws = 0
            t.runs_scored = t.runs_allowed = 0
            t.rotation_idx = 0
            t.forced_starter_idx = None
            for b in t.all_batters():
                b.reset_season()
            for p in t.all_pitchers():
                p.reset_season()
        self.schedule = generate_schedule(len(self.teams))
        self.game_idx = 0
        self.season_num += 1


# ============================================================
# 출력 도우미
# ============================================================
def show_standings(state):
    print(f"\n===== {state.season_num}시즌 순위표 =====")
    ranked = sorted(state.teams, key=lambda t: (-t.win_pct, -t.wins))
    print(f"{'순위':<4}{'구단':<14}{'경기':>4}{'승':>4}{'패':>4}{'무':>4}{'승률':>7}{'득점':>6}{'실점':>6}")
    for i, t in enumerate(ranked, 1):
        mark = " *" if state.user_team_idx is not None and state.teams[state.user_team_idx] is t else ""
        print(f"{i:<4}{t.name+mark:<14}{t.games:>4}{t.wins:>4}{t.losses:>4}{t.draws:>4}"
              f"{fmt3(t.win_pct):>7}{t.runs_scored:>6}{t.runs_allowed:>6}")


def show_roster(team):
    print(f"\n===== {team.name} 선발 라인업 =====")
    print(f"{'타순':<4}{'이름':<8}{'포지션':<6}{'컨택':>4}{'파워':>4}{'선구':>4}{'스피드':>5}"
          f"{'타율':>7}{'출루':>7}{'장타':>7}{'홈런':>5}{'타점':>5}")
    for i, b in enumerate(team.lineup, 1):
        print(f"{i:<4}{b.name:<8}{b.position:<6}{b.contact:>4}{b.power:>4}{b.eye:>4}{b.speed:>5}"
              f"{fmt3(b.avg):>7}{fmt3(b.obp):>7}{fmt3(b.slg):>7}{b.hr:>5}{b.rbi:>5}")
    print(f"\n--- 벤치 ---")
    for b in team.bench:
        print(f"     {b.name:<8}{b.position:<6}종합:{b.overall()}")

    print(f"\n===== 선발 로테이션 =====")
    for i, p in enumerate(team.rotation, 1):
        mark = " <- 다음 선발" if team.forced_starter_idx == i - 1 else ""
        print(f"{i}. {p.name:<8} 구위:{p.stuff:>3} 제구:{p.control:>3} 체력:{p.stamina:>3}  "
              f"{p.wins}승{p.losses}패 ERA {p.era:>5.2f}{mark}")
    print(f"\n===== 불펜 =====")
    for p in team.bullpen:
        print(f"{p.role:<4} {p.name:<8} 구위:{p.stuff:>3} 제구:{p.control:>3}  "
              f"{p.saves}세이브 ERA {p.era:>5.2f}")


def show_leaders(state):
    all_batters = []
    all_pitchers = []
    for t in state.teams:
        for b in t.all_batters():
            all_batters.append((t, b))
        for p in t.all_pitchers():
            all_pitchers.append((t, p))

    print("\n===== 타율 TOP 5 (규정타석 20타수 이상) =====")
    qualified = [(t, b) for t, b in all_batters if b.ab >= 20]
    qualified.sort(key=lambda x: -x[1].avg)
    for t, b in qualified[:5]:
        print(f"{b.name:<8}({t.name}) 타율 {fmt3(b.avg)}  {b.hr}홈런 {b.rbi}타점")

    print("\n===== 홈런 TOP 5 =====")
    hr_sorted = sorted(all_batters, key=lambda x: -x[1].hr)
    for t, b in hr_sorted[:5]:
        print(f"{b.name:<8}({t.name}) {b.hr}홈런  타율 {fmt3(b.avg)}")

    print("\n===== 평균자책점 TOP 5 (5이닝 이상) =====")
    p_qualified = [(t, p) for t, p in all_pitchers if p.innings >= 5]
    p_qualified.sort(key=lambda x: x[1].era)
    for t, p in p_qualified[:5]:
        print(f"{p.name:<8}({t.name}) ERA {p.era:>5.2f}  {p.wins}승{p.losses}패 {p.strikeouts}탈삼진")


def show_boxscore(home, away, result):
    n = len(result["line_home"])
    innings = [str(i) for i in range(1, n + 1)]
    print("\n" + "=" * 50)
    print(f"  {away.name}(원정)  vs  {home.name}(홈)")
    header = "     " + "".join(f"{i:>3}" for i in innings) + f"{'R':>4}{'H':>4}"
    print(header)
    away_line = "".join(f"{r:>3}" for r in result["line_away"])
    home_line = "".join(f"{r:>3}" for r in result["line_home"])
    print(f"{away.city:<5}" + away_line + f"{result['away_score']:>4}{result['away_hits']:>4}")
    print(f"{home.city:<5}" + home_line + f"{result['home_score']:>4}{result['home_hits']:>4}")
    winner = home.name if result["home_score"] > result["away_score"] else (
        away.name if result["away_score"] > result["home_score"] else "무승부")
    print(f"승리 투수 처리 등록 - 홈 선발/최종투수: {result['home_pitcher']}  "
          f"원정 최종투수: {result['away_pitcher']}")
    print(f"결과: {winner}" + (" 승리!" if winner != "무승부" else ""))
    print("=" * 50)


def edit_lineup(team):
    show_roster(team)
    print("\n타순을 바꿀 두 타순 번호를 입력하세요 (예: 1 4), 취소는 0 입력")
    raw = input("> ").strip()
    if raw == "0" or raw == "":
        return
    try:
        a, b = [int(x) for x in raw.split()]
        if 1 <= a <= 9 and 1 <= b <= 9:
            team.lineup[a - 1], team.lineup[b - 1] = team.lineup[b - 1], team.lineup[a - 1]
            print("타순을 변경했습니다.")
        else:
            print("1~9 사이의 숫자를 입력하세요.")
    except ValueError:
        print("입력을 이해하지 못했습니다.")


def set_next_starter(team):
    print(f"\n{team.name} 선발 로테이션:")
    for i, p in enumerate(team.rotation, 1):
        print(f"{i}. {p.name} (구위 {p.stuff} / 제구 {p.control} / 체력 {p.stamina})")
    raw = input("다음 경기 선발로 지정할 투수 번호 (취소 0): ").strip()
    if raw == "0" or raw == "":
        return
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(team.rotation):
            team.forced_starter_idx = idx
            print(f"{team.rotation[idx].name} 선수를 다음 경기 선발로 지정했습니다.")
        else:
            print("잘못된 번호입니다.")
    except ValueError:
        print("입력을 이해하지 못했습니다.")


# ============================================================
# 경기 진행
# ============================================================
def play_next_game(state, verbose=True):
    if state.game_idx >= len(state.schedule):
        print("\n이번 시즌 일정이 모두 종료되었습니다! '새 시즌 시작'을 선택하세요.")
        return
    h_idx, a_idx = state.schedule[state.game_idx]
    home, away = state.teams[h_idx], state.teams[a_idx]
    result = simulate_game(home, away)
    state.game_idx += 1
    involved = state.user_team_idx in (h_idx, a_idx)
    if verbose and involved:
        show_boxscore(home, away, result)
    elif verbose:
        winner = home.name if result["home_score"] > result["away_score"] else (
            away.name if result["away_score"] > result["home_score"] else "무승부")
        print(f"[{state.game_idx}/{len(state.schedule)}] {away.name} {result['away_score']} : "
              f"{result['home_score']} {home.name}  ({winner})")


def play_n_games(state, n):
    for _ in range(n):
        if state.game_idx >= len(state.schedule):
            break
        play_next_game(state, verbose=True)


def play_rest_of_season(state):
    remaining = len(state.schedule) - state.game_idx
    print(f"\n남은 {remaining}경기를 모두 시뮬레이션합니다...")
    while state.game_idx < len(state.schedule):
        play_next_game(state, verbose=False)
    print("시즌 종료!")
    show_standings(state)


# ============================================================
# 메인 메뉴
# ============================================================
def choose_team_interactively(state):
    print("\n어느 구단을 맡으시겠습니까?")
    for i, t in enumerate(state.teams, 1):
        print(f"{i}. {t.name}")
    while True:
        raw = input("> ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(state.teams):
                state.user_team_idx = idx
                print(f"\n{state.teams[idx].name}의 감독으로 부임했습니다! 화이팅!")
                return
        except ValueError:
            pass
        print("목록에 있는 번호를 입력하세요.")


def print_menu(state):
    remaining = len(state.schedule) - state.game_idx
    my_team = state.teams[state.user_team_idx].name if state.user_team_idx is not None else "-"
    print(f"\n===== KBO 매니저 (시즌 {state.season_num} / 남은 경기 {remaining}) =====")
    print(f"내 구단: {my_team}")
    print("1. 순위표 보기")
    print("2. 내 구단 로스터 보기")
    print("3. 다른 구단 로스터 보기")
    print("4. 다음 경기 시뮬레이션")
    print("5. 여러 경기 시뮬레이션")
    print("6. 남은 시즌 전체 시뮬레이션")
    print("7. 기록 리더보드")
    print("8. 타순 변경")
    print("9. 다음 선발 투수 지정")
    print("10. 저장하기")
    print("11. 불러오기")
    print("12. 새 시즌 시작")
    print("0. 종료")


def main():
    print("#" * 56)
    print("   KBO 매니저 - 텍스트 야구 매니지먼트 게임")
    print("#" * 56)

    state = None
    if os.path.exists(SAVE_FILE):
        raw = input("저장된 게임이 있습니다. 불러올까요? (y/n): ").strip().lower()
        if raw == "y":
            try:
                state = GameState.load()
                print("불러오기 완료!")
            except Exception as e:
                print(f"불러오기 실패: {e}")

    if state is None:
        state = GameState()
        choose_team_interactively(state)

    if state.user_team_idx is None:
        choose_team_interactively(state)

    while True:
        print_menu(state)
        try:
            choice = input("선택> ").strip()
        except EOFError:
            print("\n입력이 종료되어 게임을 마칩니다.")
            break

        if choice == "1":
            show_standings(state)
        elif choice == "2":
            show_roster(state.teams[state.user_team_idx])
        elif choice == "3":
            for i, t in enumerate(state.teams, 1):
                print(f"{i}. {t.name}")
            raw = input("볼 구단 번호> ").strip()
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(state.teams):
                    show_roster(state.teams[idx])
            except ValueError:
                print("잘못된 입력입니다.")
        elif choice == "4":
            play_next_game(state)
        elif choice == "5":
            raw = input("몇 경기를 시뮬레이션할까요? > ").strip()
            try:
                n = int(raw)
                play_n_games(state, n)
            except ValueError:
                print("숫자를 입력하세요.")
        elif choice == "6":
            play_rest_of_season(state)
        elif choice == "7":
            show_leaders(state)
        elif choice == "8":
            edit_lineup(state.teams[state.user_team_idx])
        elif choice == "9":
            set_next_starter(state.teams[state.user_team_idx])
        elif choice == "10":
            state.save()
            print("저장했습니다.")
        elif choice == "11":
            if os.path.exists(SAVE_FILE):
                state = GameState.load()
                print("불러오기 완료!")
            else:
                print("저장 파일이 없습니다.")
        elif choice == "12":
            if state.game_idx < len(state.schedule):
                raw = input("시즌이 아직 끝나지 않았습니다. 그래도 새 시즌을 시작할까요? (y/n): ").strip().lower()
                if raw != "y":
                    continue
            show_standings(state)
            state.new_season()
            print(f"\n{state.season_num}시즌이 시작되었습니다!")
        elif choice == "0":
            raw = input("저장하고 종료할까요? (y/n): ").strip().lower()
            if raw == "y":
                state.save()
                print("저장했습니다.")
            print("게임을 종료합니다. 감사합니다!")
            break
        else:
            print("메뉴에 있는 번호를 입력하세요.")


if __name__ == "__main__":
    main()
