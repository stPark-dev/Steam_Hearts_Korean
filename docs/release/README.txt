스팀 하츠 (세가새턴) 한글패치 v0.2.1 베타
돈골's 한글팩 — https://hangul.dongolpack.workers.dev/resources/steam-hearts/

이 판은 공개 시험판(베타)입니다. 음성 자막은 받아쓰기를 바탕으로 한 번역 초안이라
어색한 곳이 있습니다.

[v0.2.1 에서 바뀐 것]
  - 스테이지에서 게임 오버(이어하기 화면)가 되면 이미 끝난 스테이지 시작 대사 자막이
    다시 나오던 문제를 고쳤습니다.
  - 스테이지 2~8 에 들어가 시작 대사 자막이 음성에 맞춰 나오는 것을 확인했습니다
    (스테이지 7 은 앞·뒤 두 구간, 스테이지 8 은 최종 보스 대사까지).
    보스 직전·격파 대사 등 스테이지 후반 자막은 아직 확인하지 않았습니다.
  - v0.2 를 이미 적용했다면 원본에서 v0.2.1 패치를 새로 적용해야 합니다
    (패치는 원본에만 씌울 수 있습니다).

[들어 있는 파일]
  Redump\   ← 트랙별로 나뉜 BIN/CUE (Redump 판, BIN 18개)를 가진 분
    Steam-Heart's (Japan) (Track 01).bin.bps   ← 1번 트랙에 씌우는 패치
    Steam-Heart's (Korean).cue                 ← 한글판을 여는 파일
  CHD\      ← CHD 를 chdman 으로 푼 BIN 하나 + CUE 를 가진 분
    Steam-Heart's (Japan).bin.bps              ← BIN 하나에 씌우는 패치
    Steam-Heart's (Korean).cue                 ← 한글판을 여는 파일
  README.txt                                   ← 이 안내

  두 패치는 같은 한글판을 만듭니다. 가진 원본에 맞는 폴더 하나만 쓰면 됩니다.
  패치가 원본을 검사하므로 판이 다르면 적용되지 않습니다.

[가) Redump 판 — 트랙별 BIN 18개]
  원본: Steam-Heart's (Japan) (Track 01).bin   SHA-1 71cc4fc3e0613cc76c99392a2fa66cfa18fb05ef
        (Track 02) ~ (Track 18) 은 음악 트랙이라 고치지 않습니다.
  1. 원본 폴더를 통째로 복사해 둡니다(보관용).
  2. Floating IPS(flips)로 패치합니다. https://github.com/Alcaro/Flips/releases
       패치 = Redump\Steam-Heart's (Japan) (Track 01).bin.bps
       원본 = Steam-Heart's (Japan) (Track 01).bin
     저장할 이름은 반드시 아래처럼, 원본과 같은 폴더에 저장합니다.
       Steam-Heart's (Korean) (Track 01).bin
  3. Redump\Steam-Heart's (Korean).cue 를 같은 폴더에 넣습니다.
     (한글판 cue 는 한글판 Track 01 과 원본 Track 02~18 을 함께 읽습니다.)
  4. 에뮬레이터에서 Steam-Heart's (Korean).cue 를 엽니다.

[나) CHD — chdman 으로 푼 BIN 하나]
  원본 CHD 를 먼저 BIN/CUE 로 풉니다(MAME 에 들어 있는 chdman).
       chdman extractcd -i "Steam-Hearts (Japan).chd" -o "Steam-Hearts (Japan).cue"
  원본: 위에서 나온 BIN 하나 (665,787,696바이트)  SHA-1 6f7ec1792e5f87bd080ad87dd9026514cb2e88e4
        Redump 판 BIN 18개를 하나로 합친 BIN 도 이것과 같습니다.
  1. Floating IPS(flips)로 패치합니다.
       패치 = CHD\Steam-Heart's (Japan).bin.bps
       원본 = 위의 BIN
     저장할 이름: Steam-Heart's (Korean).bin
  2. CHD\Steam-Heart's (Korean).cue 를 같은 폴더에 넣고 에뮬레이터에서 엽니다.
     한글판 BIN 은 음악까지 다 들어 있어 원본 BIN 없이도 돌아갑니다.

[실행]
  Mednafen 에서 확인했습니다. RetroArch(Beetle Saturn)·SSF·Yaba Sanshiro 도 cue 를 열면 됩니다.
  세가새턴 BIOS 는 따로 준비해야 합니다.
  타이틀 화면에 한글 "스팀 하츠" 로고가 나오면 성공입니다.

[주의]
  원판은 18세 이상 이용가 성인용 게임입니다.
  실제 세가새턴 본체(CD 굽기)에서는 시험하지 않았습니다.
  이 패치는 원본 게임 데이터를 포함하지 않습니다. 원본 파일 요청은 받지 않습니다.
  오류·오역 제보: https://hangul.dongolpack.workers.dev/reports/?resource=steam-hearts
    (스테이지/장면 번호와 대략 어느 대사인지 알려 주시면 고치기 쉽습니다)
