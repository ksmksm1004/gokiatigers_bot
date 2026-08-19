# gokiatigers_bot

KIA 타이거즈 경기를 감시해 경기 전 정보, 실시간 중계, 경기 종료 기록과 관련 콘텐츠를 텔레그램으로 보내는 Python 봇입니다.

네이버 스포츠 JSON API를 중심으로 네이버 날씨, TVING SPORTS YouTube 피드, 네이버 경기 영상 데이터를 함께 사용합니다. 시간 기준은 `Asia/Seoul`입니다.

## 주요 기능

- 당일 KIA 경기 자동 탐색 및 경기 상태 추적
- 경기 프리뷰, 양 팀 선발 라인업과 선수 사진 발송
- KIA 공격 시작·종료 및 주요 플레이 실시간 알림
- 타자·투수 사진, 누적 타격 기록, 아웃 카운트 표시
- 경기 종료 스코어, 하이라이트 타자, KIA 박스스코어 발송
- 승리·패전투수, 홀드, 세이브가 늦게 확정될 때 후속 업데이트
- 모든 KBO 경기 종료 후 당일 전체 스코어와 팀 순위 발송
- 경기 종료 10분 뒤 KIA 관련 기사 발송
- TVING SPORTS YouTube 하이라이트와 네이버 쇼츠 발송
- 우천·폭염 등 경기 취소 사유 판별
- 일정, 순위, 월간 성적, 팀·타자·투수 기록, 뉴스, 날씨 명령 지원
- `logs/state.json`을 이용한 재시작 복구 및 중복 발송 방지

## 자동 알림 흐름

### 경기 전

프리뷰는 당일 경기를 찾은 뒤 데이터가 준비되는 즉시 발송할 수 있습니다. 기본적으로 예정 시작 60분 전부터 경기 상태와 라인업을 집중적으로 확인합니다.

1. **경기 프리뷰**
   - 양 팀 순위, 승·무·패, 승률
   - 팀 타율과 평균자책점
   - 선발투수 시즌 승패, ERA, WHIP
   - KIA와 상대 팀의 최근 5경기
   - 시즌 상대전적
   - 네이버 문자중계 링크
2. **선발 라인업**
   - 양 팀 선발투수와 1~9번 타자
   - 선수 사진, 타순, 포지션, 투타 정보
   - 양 팀 모두 선발투수와 1~9번 타자가 확인된 뒤 발송

프리뷰 데이터가 아직 없으면 다음 정각에 다시 확인합니다. 라인업은 경기 전 기본 5분 간격으로 확인하며, 경기 시작 후에도 아직 발송되지 않았다면 계속 확인합니다.

### 실시간 중계

경기 시작 후 기본 5초 간격으로 네이버 문자중계를 확인합니다. `seqno`를 상태 파일에 저장해 이미 처리한 이벤트는 다시 보내지 않습니다.

#### KIA 공격 시작

- 이닝과 현재 스코어
- 직전 상대 공격의 아웃 결과
- 예상 타자 3명의 타율과 당일 안타/타수
- 직전 수비에서 등판한 KIA 투수의 투구 수와 기록

직전 상대 공격은 아웃 순서에 따라 다음과 같이 표시됩니다.

```text
KIA 공격 시작 | 7회초
KIA 3 : 2 한화 (삼진1 병살타23)
KIA 예상 타자
1 박재현 | .284 | 1-3
2 김선빈 | .272 | 0-2
3 김도영 | .294 | 0-2
```

#### KIA 공격 종료

해당 반이닝에 타석에 들어선 선수의 누적 경기 기록을 보여줍니다. 아웃을 만든 선수에게는 결과와 실제 아웃 번호를 붙이고, 마지막에는 그 이닝에 KIA를 상대한 상대 투수의 누적 기록을 표시합니다. 한 이닝에 투수가 여러 명 등판하면 모두 표시합니다.

```text
KIA 공격 종료 | 7회초
KIA 4 : 2 한화
1 박재현 | .286 | 4타수 2안타 1타점 | 태그2
2 김선빈 | .271 | 3타수 1볼넷 | 땅볼1
3 김도영 | .296 | 3타수 1득점 1안타 1타점 1홈런 1볼넷 2삼진
4 카스트로 | .350 | 4타수 1득점 2안타 | 플라이3

화이트(한) | 103개 | 7이닝 5피안타 2실점 2자책 2사사구 6삼진 ERA 3.11
```

아웃 번호는 각 중계 이벤트의 `currentGameState.out` 증가량으로 계산합니다. 병살로 아웃이 `1→3`처럼 한 번에 증가하면 `병살타23`으로 표시하고, 비디오 판독으로 아웃 수가 되돌아가면 취소된 아웃 기록을 제거합니다.

#### 주요 플레이

- KIA 타자의 안타, 장타, 홈런
- 볼넷, 사구, 희생번트, 희생플라이
- KIA 공격 중 도루와 득점
- 비디오 판독
- 양 팀 투수 교체
- 경기 종료 관련 이벤트

공격 시작·종료를 제외한 중계, 득점, 교체 메시지 제목에는 현재 아웃 수를 표시합니다.

```text
중계 | 7회말 (2 out)
```

KIA 타자의 주요 타석 결과와 득점에는 해당 선수 사진을 붙입니다. KIA 투수 교체 때는 새로 등판하는 투수의 사진을 붙이며, 상대 팀 투수 교체는 텍스트로만 보냅니다.

### 경기 종료 후

KIA 경기 종료가 문자중계에서 확인되면 다음 내용을 보냅니다.

1. 당일 주요 타자 하이라이트
2. 최종 스코어
3. 승리투수, 패전투수, 홀드, 세이브
4. KIA 타격 합계와 타자별 기록
5. KIA 투구 합계와 투수별 기록
6. 경기 종료 확인 메시지

네이버가 투수 판정을 늦게 제공하면 스코어와 박스스코어를 먼저 보내고, 60초 간격으로 다시 확인해 `투수 판정 업데이트`를 별도로 보냅니다.

경기 기록이 처음 확인된 시점으로부터 약 10분 뒤 KIA 관련 기사 최대 5개를 보냅니다. 기사가 아직 없으면 10분 간격으로 최대 3회 확인합니다.

당일 모든 KBO 경기가 종료되거나 취소된 뒤에는 다음 순서로 발송합니다.

1. 당일 전체 KBO 경기 스코어 또는 취소 여부
2. KBO 팀 순위, 게임 차, 연승·연패, 최근 10경기
3. TVING SPORTS YouTube의 당일 KIA 경기 하이라이트
4. 네이버 경기 쇼츠 최대 5개

YouTube 하이라이트와 네이버 쇼츠가 아직 등록되지 않았다면 각각 10분 간격으로 최대 12회 확인합니다. 쇼츠는 링크 하나당 텔레그램 메시지 하나로 보냅니다.

### 경기 취소

네이버 경기 정보에 취소 사유가 있으면 해당 값을 우선 사용합니다. 사유가 없을 때는 경기장 현재 날씨를 확인합니다.

- 비, 소나기, 뇌우, 눈 또는 강수량이 있으면 `우천 취소`
- 맑음 또는 강수량 0mm이면 `폭염 취소`
- 어느 쪽도 판단할 수 없으면 `경기 취소`

## 텔레그램 명령어

봇은 설정한 `TELEGRAM_CHAT_ID`에서 온 명령만 처리합니다. 텔레그램 명령 메뉴에는 영문 명령이 등록되며 한글 명령도 직접 입력할 수 있습니다.

| 한글 명령 | 영문 명령 | 기능 |
| --- | --- | --- |
| `/라인업` | `/lineup` | 오늘 경기 양 팀 선발 라인업과 선수 사진 |
| `/일정` | `/schedule` | 오늘 이후 KIA 경기 일정을 최대 4개 연전 단위로 표시 |
| `/기록` | `/record` | 오늘 KIA 경기 타자·투수 박스스코어 |
| `/순위` | `/rank` | 시즌 팀 순위, 게임 차, 연속 경기 결과, 최근 10경기 |
| `/월간성적` | `/monthlyrecord` | 현재 월 종료 경기 기준 전체 팀 승·패·무와 승률 |
| `/팀기록` | `/teamrecord` | 팀 주요 기록 종목 선택 |
| `/타자기록 [선수명]` | `/hitterrecord [선수명]` | 타자 주요 기록 TOP 10 종목 선택 또는 개인 기록 조회 |
| `/투수기록 [선수명]` | `/pitcherrecord [선수명]` | 투수 주요 기록 TOP 10 종목 선택 또는 개인 기록 조회 |
| `/뉴스` | `/news` | 중복을 제거한 KIA 관련 기사 최대 10개 |
| `/날씨` | `/weather` | 오늘 경기장 현재 날씨와 향후 8시간 예보 |
| `/gg` | `/gg` | 경기 중 실시간 플레이 알림만 중단하고 종료 기록·순위·후속 콘텐츠는 유지 |
| `/re` | `/re` | 중단한 중계를 최신 이벤트부터 재개 |
| `/도움말`, `/명령어` | `/help`, `/start` | 사용 가능한 명령 목록 |

### 기록 명령 사용법

`/팀기록`, `/타자기록`, `/투수기록`을 입력하면 인라인 버튼과 번호 목록이 표시됩니다. 버튼을 누르거나 종목명만 후속 메시지로 보낼 수 있습니다.

```text
/팀기록 타율
타율
타율 알려줘
```

지원 종목은 다음과 같습니다.

| 구분 | 종목 |
| --- | --- |
| 팀 기록 | 타율, 평균자책, 홈런, 안타, 도루, 득점, 실점 |
| 타자 기록 | 타율, 홈런, 타점, 도루, OPS, WAR |
| 투수 기록 | 승, 평균자책, 탈삼진, 세이브, WHIP, WAR |

타자와 투수 기록은 상위 10명까지 표시합니다. 타율과 OPS, 투수 평균자책과 WHIP는 네이버의 `isQualified` 값을 사용해 규정 타석·이닝 충족 선수만 포함합니다.

선수명을 명령 뒤에 붙이면 KBO 공식 선수 페이지에서 사진, 기본정보와 현재 시즌 기록을 조회합니다.

```text
/타자기록 김도영
/hitterrecord 김도영
/투수기록 양현종
/pitcherrecord 양현종
```

- 타자: 이름, 생년월일, 신장/체중, 연봉, 등번호, 포지션, 타율, 타수, 안타, 2루타, 3루타, 홈런, 타점, 득점, 도루, 사사구, 삼진, 출루율, 장타율, OPS
- 투수: 이름, 생년월일, 신장/체중, 연봉, 등번호, 포지션, 평균자책, 이닝, 승, 패, 세이브, 홀드, 탈삼진, 피안타, 피홈런, 사사구, 실점, 자책점, WHIP

검색 결과에 같은 이름과 같은 선수 유형이 여러 명이면 팀, 포지션, 등번호, 투타 정보가 표시된 인라인 버튼으로 선수를 선택합니다. 현역 등록 선수와 이름이 정확히 일치하는 결과만 사용합니다.

### 월간 성적 계산

월간 성적은 별도 누적 JSON을 만들지 않습니다. 명령을 실행할 때 네이버 월간 일정에서 상태가 `RESULT`인 경기만 집계합니다.

- 진행 중, 예정, 취소 경기는 제외
- 승률은 `승 / (승 + 패)`로 계산하고 무승부는 분모에서 제외
- 승률이 같으면 공동 순위로 표시하고 다음 순위는 건너뜀
- 네이버 결과가 정정되면 다음 명령 실행 때 자동 반영

## 설치

Python 3.10 이상을 권장합니다.

```bash
cd /path/to/gokiatigers_bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 텔레그램 봇 토큰과 대상 채팅 ID를 입력합니다.

```dotenv
TELEGRAM_TOKEN=botfather_token
TELEGRAM_CHAT_ID=your_chat_id
TEAM_CODE=HT
```

## 환경변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | 없음 | BotFather에서 발급한 토큰. `DRY_RUN`이 아니면 필수 |
| `TELEGRAM_CHAT_ID` | 없음 | 메시지를 보내고 명령을 받을 채팅 ID. `DRY_RUN`이 아니면 필수 |
| `TEAM_CODE` | `HT` | 감시 대상 팀 코드. 현재 메시지와 기능은 KIA 기준으로 설계됨 |
| `POLL_SECONDS` | `5` | 경기 중 문자중계 조회 간격(초) |
| `IDLE_POLL_SECONDS` | `300` | 비실시간 상태와 전체 경기 종료 대기 기본 간격(초) |
| `SCHEDULE_CHECK_SECONDS` | `21600` | 경기 미발견·일정 재확인 시 사용하는 최대 기본 간격(초) |
| `PREGAME_POLL_SECONDS` | `300` | 경기 전 라인업·상태 조회 간격(초) |
| `PREGAME_MINUTES` | `60` | 예정 시작 몇 분 전부터 집중 감시할지 설정 |
| `POSTGAME_MINUTES` | `30` | 예정 시작 5시간 뒤 추가 집중 감시 시간(분) |
| `NAVER_GAME_ID` | 없음 | 자동 경기 검색 실패 시 당일 경기 ID 강제 지정 |
| `DRY_RUN` | 꺼짐 | `1`, `true`, `yes`, `y`이면 텔레그램 대신 콘솔 출력 |

당일 경기를 찾지 못하면 기본적으로 09시, 12시, 15시, 17시, 18시, 19시, 20시, 21시에 다시 일정을 확인하고, 이후에는 다음 날 09시에 확인합니다. 대기 중에도 텔레그램 명령과 예약된 뉴스·영상 발송은 최대 5초 단위로 계속 확인합니다.

자동 검색이 실패할 때만 다음 값을 사용합니다.

```dotenv
NAVER_GAME_ID=20260702SKHT02026
```

## 실행

### 드라이런

텔레그램으로 보내지 않고 콘솔과 로그에서 메시지를 확인합니다. 드라이런에서는 토큰과 채팅 ID를 생략할 수 있습니다.

```bash
DRY_RUN=1 python3 bot.py
```

### 포그라운드 실행

```bash
python3 bot.py
```

### 백그라운드 실행

```bash
mkdir -p logs
nohup .venv/bin/python3 bot.py > logs/nohup.out 2>&1 &
```

로그 확인:

```bash
tail -f logs/bot.log
```

## 테스트

```bash
source .venv/bin/activate
python3 -m py_compile bot.py config.py naver_api.py naver_weather.py parser.py telegram.py youtube.py
python3 -m unittest
```

특정 테스트 파일만 실행할 수도 있습니다.

```bash
python3 -m unittest test_parser
python3 -m unittest test_bot
python3 -m unittest test_naver_api test_weather test_telegram test_youtube
```

## 상태와 재시도

### 상태 파일

런타임 상태는 `logs/state.json`에 저장됩니다. 저장할 때 임시 파일을 만든 뒤 교체하므로 쓰기 도중 프로세스가 종료되어도 파일 손상 가능성을 줄입니다.

주요 저장 항목:

- 당일 경기 ID와 일정 캐시
- 마지막 문자중계 `seqno`
- 이미 보낸 프리뷰, 라인업, 공격 종료, 경기 종료 표시
- 타자별 타석 결과와 타점 기준값
- 투수 판정, 전체 스코어, 순위 발송 상태
- 뉴스, YouTube 하이라이트, 네이버 쇼츠 재시도 시각과 횟수
- 텔레그램 `getUpdates` 오프셋

`logs/state.json`을 삭제하면 봇이 당일 상태를 새로 구성합니다. 경기 도중 삭제하면 일부 알림이 다시 발송될 수 있으므로 봇을 중지한 상태에서만 삭제하는 편이 안전합니다.

### 재시도 정책

| 대상 | 정책 |
| --- | --- |
| 네이버 JSON 요청 | 연결 오류와 일부 일시적 서버 오류를 최대 3회 재시도 |
| 텔레그램 명령 조회 | 연결 실패 시 한 번 재시도 후 해당 주기 건너뜀 |
| 텔레그램 429 제한 | Telegram의 `retry_after`를 반영해 한 번 재전송 |
| 경기 프리뷰 | 준비되지 않았거나 조회 실패 시 다음 정각에 재확인 |
| 투수 승·패 판정 | 경기 기록 발송 후 60초 간격으로 재확인 |
| 경기 후 KIA 기사 | 최초 10분 뒤부터 10분 간격, 최대 3회 |
| YouTube 하이라이트 | 전체 경기 종료 후 10분 간격, 최대 12회 |
| 네이버 쇼츠 | 하이라이트 확인 후 10분 간격, 최대 12회 |

## macOS LaunchAgent 등록

재부팅 후에도 자동 실행하려면 저장소와 가상환경의 절대 경로를 사용해 LaunchAgent를 등록합니다. 아래 예시는 `/Users/YOUR_USER/apps/gokiatigers_bot`에 프로젝트가 있는 경우입니다.

```bash
APP_DIR="/Users/YOUR_USER/apps/gokiatigers_bot"
cd "$APP_DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p logs
```

`certifi` CA 파일 경로를 확인합니다. plist의 `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` 값은 이 출력과 같아야 합니다.

```bash
"$APP_DIR/.venv/bin/python3" -c "import certifi; print(certifi.where())"
```

`~/Library/LaunchAgents/com.gokiatigers.bot.plist`를 생성합니다. plist 안에서는 `~`와 `$HOME`이 자동 확장되지 않으므로 모두 절대 경로를 사용해야 합니다.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">

<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gokiatigers.bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USER/apps/gokiatigers_bot/.venv/bin/python3</string>
        <string>/Users/YOUR_USER/apps/gokiatigers_bot/bot.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USER/apps/gokiatigers_bot</string>

    <key>StandardOutPath</key>
    <string>/Users/YOUR_USER/apps/gokiatigers_bot/logs/launchd.out</string>

    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USER/apps/gokiatigers_bot/logs/launchd.err</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>SSL_CERT_FILE</key>
        <string>/absolute/path/to/certifi/cacert.pem</string>
        <key>REQUESTS_CA_BUNDLE</key>
        <string>/absolute/path/to/certifi/cacert.pem</string>
    </dict>
</dict>
</plist>
```

문법과 권한을 확인한 뒤 등록합니다.

```bash
plutil -lint ~/Library/LaunchAgents/com.gokiatigers.bot.plist
chmod 644 ~/Library/LaunchAgents/com.gokiatigers.bot.plist
chown "$(id -un)":staff ~/Library/LaunchAgents/com.gokiatigers.bot.plist

launchctl bootout gui/$(id -u)/com.gokiatigers.bot 2>/dev/null
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.gokiatigers.bot.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gokiatigers.bot.plist
launchctl kickstart -k gui/$(id -u)/com.gokiatigers.bot
```

상태와 로그 확인:

```bash
launchctl print gui/$(id -u)/com.gokiatigers.bot
ps aux | grep gokiatigers_bot | grep -v grep
tail -f "$APP_DIR/logs/bot.log"
tail -f "$APP_DIR/logs/launchd.err"
```

코드나 의존성을 변경한 뒤 다시 실행:

```bash
cd "$APP_DIR"
source .venv/bin/activate
pip install -r requirements.txt
python3 -m unittest
launchctl kickstart -k gui/$(id -u)/com.gokiatigers.bot
```

`Bootstrap failed: 5`가 나오면 plist 문법, 파일 권한, 기존 job 등록 상태를 확인합니다.

```bash
plutil -lint ~/Library/LaunchAgents/com.gokiatigers.bot.plist
launchctl bootout gui/$(id -u)/com.gokiatigers.bot 2>/dev/null
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.gokiatigers.bot.plist 2>/dev/null
log show --predicate 'process == "launchd"' --last 2m | grep gokiatigers
```

이전 경로의 프로세스가 남아 있으면 해당 절대 경로를 확인한 뒤 종료합니다.

```bash
pkill -f "/old/path/to/gokiatigers_bot/bot.py"
pkill -f "/old/path/to/gokiatigers_bot/.venv"
```

## 프로젝트 구성

| 파일 | 역할 |
| --- | --- |
| `bot.py` | 메인 루프, 상태 관리, 명령 처리, 알림 예약과 발송 |
| `config.py` | `.env` 로드와 실행 설정 |
| `kbo_api.py` | KBO 선수 검색, 개인 기본정보·현재 시즌 기록 파싱과 메시지 포맷 |
| `naver_api.py` | 네이버 스포츠 일정·프리뷰·중계·기록·뉴스·영상 API 클라이언트 |
| `naver_weather.py` | 경기장 위치 매핑, 네이버 날씨 파싱과 예보 출력 |
| `parser.py` | API 응답 파싱, 중계 판정, 기록 집계와 메시지 포맷 |
| `telegram.py` | Telegram Bot API 메시지, 사진, 미디어 그룹, 명령 처리 |
| `youtube.py` | TVING SPORTS YouTube Atom 피드에서 KIA 하이라이트 검색 |
| `test_*.py` | 파서, 봇 흐름, API, 날씨, Telegram, YouTube 단위 테스트 |

## 데이터 소스와 제한사항

- 네이버 스포츠의 공개 웹 JSON 응답을 사용하므로 필드나 주소가 바뀌면 파서 수정이 필요할 수 있습니다.
- 개인 선수 기록은 KBO `Basic.aspx`를 기준으로 하며, 투수 사사구 계산에 필요한 몸에 맞는 공만 같은 선수의 `Total.aspx` 현재 연도 행에서 보충합니다.
- KBO 선수 검색과 상세 페이지 구조가 바뀌면 개인 기록 검색 또는 파서 수정이 필요할 수 있습니다.
- 투수 판정, 기사, 하이라이트, 쇼츠는 경기 종료 직후 바로 제공되지 않을 수 있으며 위 재시도 정책에 따라 후속 발송됩니다.
- 월간 성적은 현재 월의 종료 경기만 실시간 계산하며 과거 월 기록을 별도 저장하지 않습니다.
- 경기 취소 사유가 API에 없을 때 날씨로 우천·폭염을 추정하므로 공식 사유와 다를 수 있습니다.
- 하나의 프로세스와 하나의 `TELEGRAM_CHAT_ID` 사용을 전제로 합니다.
- 선수 사진은 네이버 선수 이미지 URL을 사용하며, 필요한 경우 코드 내 개별 선수 URL 예외가 적용됩니다.

## 보안

- `.env`, 텔레그램 토큰, 채팅 ID를 Git에 커밋하지 마세요.
- 로그나 오류 메시지를 공유하기 전에 토큰과 개인 채팅 정보를 제거하세요.
- LaunchAgent plist에는 토큰을 직접 넣지 않고 프로젝트의 `.env`를 사용하세요.
