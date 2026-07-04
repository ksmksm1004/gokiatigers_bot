# gokiatigers_bot

KIA 타이거즈 경기만 감시하는 네이버 스포츠 JSON API 기반 텔레그램 중계 봇입니다.

## 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`를 열어 아래 값을 채워주세요.

```bash
TELEGRAM_TOKEN=botfather_token
TELEGRAM_CHAT_ID={YOUR_CHAT_ID}
TEAM_CODE=HT
```

자동 경기 검색이 실패하면 당일 경기 ID를 직접 고정할 수 있습니다.

```bash
NAVER_GAME_ID=20260702SKHT02026
```

## 실행

테스트 발송 없이 메시지 내용을 콘솔에서 확인:

```bash
DRY_RUN=1 python bot.py
```

백그라운드 실행:

```bash
nohup python3 bot.py > logs/nohup.out 2>&1 &
```

## 동작

- 오늘 KIA 경기 일정을 찾습니다.
- 경기 시작 60분 전부터 프리뷰, 순위, 최근 5경기, 상대전적, 선발투수를 보냅니다.
- 선발 라인업이 발표되면 양팀 선발투수와 1~9번 타자를 선수 사진, 순번, 포지션과 함께 한 번 보냅니다.
- 경기 중 5초마다 릴레이를 확인합니다.
- KIA 공격 시작 때 예상 타자 3명과 현재 타수/안타를 보냅니다.
- KIA 타자의 안타, 사사구, 희생플라이, 도루와 득점 이벤트, 투수 교체, 경기 종료를 텔레그램으로 보냅니다.
- KIA 타자의 진루 결과는 네이버 선수 이미지 URL을 `sendPhoto`로 함께 보냅니다.
- `logs/state.json`에 마지막 릴레이 번호를 저장해 재시작 후 중복 발송을 줄입니다.

## 주의

텔레그램 토큰은 절대 커밋하지 마세요. 
