# Jetson에서 Hugging Face Laya를 GPU로 실행하기

## 적용 이유

이 프로젝트에서는 Hugging Face의 `convaiinnovations/laya-multilingual` checkpoint를 Python 프로세스에 직접
불러와 Jetson CUDA로 실행한다.

기존 Ollama 기반 생성형 모델 코드는 별도의 실행 경로로 유지한다.

## 대상 장비와 메모리 정책

- 장비: Jetson Orin Nano Developer Kit, RAM 8GB
- 프로젝트에서 사용할 수 있는 RAM: 약 4.5GB
- 사용할 수 있는 저장공간: 약 15GB
- 모델: multilingual checkpoint 하나만 로드
- 기본 입력 한도: 1,024 tokens
- 동시 추론: 한 번에 한 요청
- CUDA를 사용할 수 없거나 CPU fallback이 발생하면 즉시 오류 처리

Laya Router의 `preload=True`는 여러 checkpoint를 함께 메모리에 올리므로 이
환경에서는 사용하지 않는다. TileLang fast extra도 먼저 설치하지 않는다.
기본 CUDA 경로를 검증한 다음 필요할 때 별도로 평가한다.

## 코드 구성

- `simulation/route_selector/laya_selector.py`: Hugging Face 모델 로드 및 typed decision 처리
- `simulation/route_selector/registry.py`: `laya` selector 등록
- `simulation/requirements-laya-jetson.txt`: Jetson에서만 설치하는 Laya 의존성
- `tests/test_laya_selector.py`: 모델을 받지 않는 Mock 구조 테스트

모델 파일은 Git에 저장하지 않는다. 첫 실행 시 Hugging Face cache로 내려받으며
`laya-multilingual` checkpoint는 약 647MB다. Python 환경과 JetPack용 PyTorch가
차지하는 공간은 별도이므로 설치 전 `df -h`로 확인한다.

## 1. Jetson CUDA PyTorch 확인

JetPack 버전에 맞는 NVIDIA 제공 PyTorch를 먼저 설치해야 한다. 일반 PyPI의
CPU용 PyTorch로 교체하지 않는다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -c "import torch; print('torch=', torch.__version__); print('cuda=', torch.cuda.is_available()); print('device=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
```

반드시 다음 조건을 만족해야 한다.

```text
cuda= True
device= Orin
```

`cuda=False`이면 Laya를 설치하기 전에 JetPack 버전과 맞는 PyTorch를 설치한다.

## 2. 여유 공간 확인 및 cache 위치 지정

```bash
df -h ~
free -h
mkdir -p ~/.cache/huggingface
export HF_HOME="$HOME/.cache/huggingface"
```

15GB 한도 안에서 Hugging Face cache를 한 위치로 고정해 중복 다운로드를
방지한다. `HF_HOME`은 실행하는 모든 터미널에서 같은 값을 사용한다.

## 3. Laya 런타임 설치

CUDA가 동작하는 기존 PyTorch 환경에서 설치한다.

```bash
python -m pip install -r simulation/requirements-laya-jetson.txt
python -m pip check
```

설치 뒤에도 Jetson CUDA PyTorch가 유지됐는지 다시 확인한다.

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

## 4. 환경변수 설정

`simulation/.env`에 다음 값을 설정한다.

```dotenv
ROUTE_SELECTOR=laya
LAYA_HF_MODEL=convaiinnovations/laya-multilingual
LAYA_DEVICE=cuda:0
LAYA_REQUIRE_CUDA=true
LAYA_MAX_LENGTH=1024
HF_HOME=/home/sein/.cache/huggingface
# 공개 모델에는 HF_TOKEN이 필요하지 않다.
# HF_TOKEN=
```

`LAYA_REQUIRE_CUDA=true`이므로 CUDA를 사용할 수 없을 때 CPU로 조용히
전환하지 않고 오류가 발생한다. GPU 성능 시험에 CPU 결과가 섞이는 것을 막기
위한 설정이다.

## 5. 모델 다운로드 없이 구조 테스트

```bash
python -m unittest tests.test_laya_selector -v
```

이 테스트는 가짜 CUDA agent를 주입하므로 Hugging Face 접속이나 실제 GPU가
필요하지 않다.

## 6. 실제 GPU smoke test

첫 실행에서 checkpoint를 다운로드하므로 시간이 더 걸린다.

```bash
python - <<'PY'
from simulation.route_selector import get_selector

selector = get_selector()
try:
    result = selector.select_route(
        {"start_node": 2, "target_node": 10},
        {
            "route_a": "path=[2,5,4,6,13,8,9,10], distance=3.033652",
            "route_b": "path=[2,5,4,6,10], distance=1.592143",
        },
    )
    print("choice:", result["choice"])
    print("confidence:", result["confidence"])
    print("runtime:", result["runtime"])
    print("load_seconds:", result["load_duration_seconds"])
    print("eval_seconds:", result["eval_duration_seconds"])
finally:
    selector.release()
PY
```

정상 결과에는 다음 값이 포함되어야 한다.

```text
runtime: {'device': 'cuda:0', 'precision': 'float16' 또는 'bfloat16', ...}
```

다른 터미널에서 Jetson 사용량도 확인한다.

```bash
sudo tegrastats
```

## 7. 오류 확인

### CUDA를 사용할 수 없다는 오류

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

`False`이면 코드 문제가 아니라 현재 가상환경의 PyTorch가 Jetson CUDA를
지원하지 않는 상태다.

### CUDA 메모리 부족

```bash
free -h
sudo tegrastats
```

다른 모델 서버와 불필요한 프로세스를 종료하고 `LAYA_MAX_LENGTH`를 512로
낮춰 다시 확인한다. selector는 한 번에 한 요청만 실행하고, `release()`를
호출하면 모델과 CUDA cache를 해제한다.

### 저장공간 확인

```bash
du -sh "$HF_HOME"
df -h ~
```

cache 전체를 임의로 삭제하면 다음 실행 때 모델을 다시 다운로드한다. 모델
파일은 Git에 추가하지 않는다.
