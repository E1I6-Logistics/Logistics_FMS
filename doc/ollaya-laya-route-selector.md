# Ollaya 기반 Laya 경로 후보 선택기

## 목적

Ollaya가 로컬에서 제공하는 Laya 의사결정 모델로 여러 경로 후보 중 하나를
선택한다. 경로 자체를 생성하거나 최단 거리를 계산하지 않는다. 최단 경로와
거리 계산은 기존 `route_service`가 담당하고, Laya는 이미 만들어진 후보를
선택하는 역할만 담당한다.

Ollaya와 Ollama는 서로 다른 프로그램이다. Ollama는 생성형 LLM 서버이고,
Ollaya는 Laya 같은 의사결정 모델을 제공하며 기본 포트는 `11435`이다.

## 코드 구성

- `simulation/route_selector/base.py`: 후보 선택기의 공통 인터페이스
- `simulation/route_selector/ollaya_laya_selector.py`: Ollaya `/api/decide` 호출
- `simulation/route_selector/registry.py`: `ROUTE_SELECTOR` 값으로 구현 선택
- `tests/test_ollaya_laya_selector.py`: 서버 없이 요청·응답 형식 검증

요청에는 상태와 두 개 이상의 후보를 전달한다. Ollaya 응답에서는 선택 ID,
신뢰도, 후보별 확률, 실제 checkpoint, 라우팅 정보와 실행 시간을 기록한다.
`laya` 모델명은 입력 언어에 따라 영어 또는 다국어 checkpoint를 자동 선택한다.

## 설치 및 서버 준비

원격 Linux 또는 WSL 터미널에서 Ollaya를 설치한다.

```bash
curl -fsSL https://ollaya.dev/install.sh | sh
ollaya --version
ollaya pull laya
ollaya list
```

설치 과정에서 서비스가 자동 시작되지 않았다면 별도 터미널에서 실행한다.

```bash
ollaya serve
```

서버 상태와 모델을 확인한다.

```bash
curl http://127.0.0.1:11435/api/tags
ollaya run laya --preset triage --verbose   "배송 로봇의 이동 경로를 선택해야 합니다."
```

## 프로젝트 설정

`simulation/.env`에 다음 값을 넣는다.

```dotenv
ROUTE_SELECTOR=ollaya_laya
OLLAYA_HOST=http://127.0.0.1:11435
OLLAYA_MODEL=laya
OLLAYA_TIMEOUT_SECONDS=10
# 서버에 OLLAYA_API_KEY를 설정한 경우에만 같은 값을 입력한다.
# OLLAYA_API_KEY=
```

Ollaya가 다른 컴퓨터에서 실행된다면 `OLLAYA_HOST`에 그 컴퓨터의 주소를
입력한다. 외부 접속 허용 범위와 방화벽 설정은 해당 장비에서 별도로 제한한다.

## 코드 구조 테스트

이 테스트는 Ollaya나 모델을 실행하지 않는다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m unittest tests.test_ollaya_laya_selector -v
```

## Python에서 호출

```python
from simulation.route_selector import get_selector

selector = get_selector()
result = selector.select_route(
    {"start_node": 2, "target_node": 10},
    {
        "route_a": "path=[2,5,4,6,13,8,9,10], distance=3.033652",
        "route_b": "path=[2,5,4,6,10], distance=1.592143",
    },
)
print(result)
```

반환값의 주요 필드는 다음과 같다.

- `choice`: 선택된 후보 ID
- `confidence`: 선택 신뢰도
- `probabilities`: 후보별 확률
- `model`: 실제 응답한 Laya checkpoint
- `total_duration_seconds`: 로딩을 포함한 전체 처리 시간
- `load_duration_seconds`: 모델 로딩 시간
- `eval_duration_seconds`: 추론 시간
- `raw`: Ollaya 원시 응답

후보 순서를 무작위로 바꾸어 정확도를 측정하는 3차 반복 테스트는 이 선택기를
사용해 별도 단계에서 구현한다.
