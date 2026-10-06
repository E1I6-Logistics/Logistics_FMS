# 로컬 모델 경로 생성·선택 벤치마크

코드가 계산한 최단 경로와 로컬 모델의 결과를 비교한다.

- **Ollama 경로 생성 시험**: 모델이 최단 경로를 직접 생성한다.
- **Laya·Kev 경로 선택 시험**: 코드가 만든 경로 후보 중 하나를 선택한다.

두 시험은 서로 다른 과제이므로 결과를 같은 지표로 해석하지 않는다. 이 실행기는
로봇 이동 명령을 보내지 않으며 FastAPI, ROS 2, Zenoh, 데이터베이스를 사용하지 않는다.

모델 선정 근거, 과거 결과, 상세 문제 해결 방법은
[`llm-route-generation-benchmark-reference.md`](./llm-route-generation-benchmark-reference.md)에
정리한다.

## 1. 시험 환경

| 항목 | PC | Jetson |
| --- | --- | --- |
| 장비 | 데스크톱 | Jetson Orin Nano Developer Kit |
| CPU | Intel Core i7-11700 | Cortex-A78AE 6코어 (`aarch64`) |
| GPU | GeForce RTX 4070 SUPER (VRAM 12GB) | Orin 내장 GPU (CPU와 메모리 공유) |
| 메모리 | 32GB | 8GB (프로젝트 사용 가능 약 4.5GB) |
| 저장장치 | Samsung 970 EVO Plus 1TB | 64GB SD 카드 (프로젝트 사용 가능 약 15GB) |

두 장비의 결과를 비교할 때는 Git 커밋, checkpoint, 입력, 반복 횟수와 모델 설정을
같게 유지한다. 출력 폴더 이름만 `pc-rtx4070`과 `jetson-orin`으로 구분한다.

## 2. 공통 설치

### 2.1 저장소와 Python 확인

```bash
cd ~/Logistics_FMS
git branch --show-current
git rev-parse HEAD
git status --short
python3 --version
df -h /
free -h
```

Kev는 Python 3.12 이상 3.14 미만을 요구한다. PC와 Jetson에서 같은 Python 3.12
가상환경을 사용한다.

가상환경이 없다면 한 번만 생성한다.

```bash
python3 -m venv ~/venv/robot
source ~/venv/robot/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

이미 있다면 활성화만 한다.

```bash
source ~/venv/robot/bin/activate
```

### 2.2 Jetson CUDA PyTorch 설치

Jetson에서는 프로젝트 requirements보다 먼저 검증된 CUDA PyTorch를 설치한다.

```bash
source ~/venv/robot/bin/activate

python -m pip install \
  --no-cache-dir \
  --force-reinstall \
  "torch==2.8.0" \
  --index-url https://download.pytorch.org/whl/cu129
```

PC에 CUDA PyTorch가 이미 설치되어 있다면 이 단계는 생략한다.

### 2.3 프로젝트 의존성 설치

Ollama provider와 Laya 의존성은 하나의 파일에서 관리한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m pip install -r simulation/requirements.txt
python -m pip check
```

Laya를 포함한 Python 패키지는 `simulation/requirements.txt`에서 통합 관리한다.

### 2.4 환경변수 파일 생성

```bash
cd ~/Logistics_FMS
cp -n simulation/.env.example simulation/.env
```

`simulation/.env`에는 API key를 커밋하지 않는다. Laya와 Kev 선택기는 이 파일을
자동으로 읽는다. Ollama 경로 생성 벤치마크는 현재 이 파일을 자동으로 읽지 않으므로
원격 Ollama 주소는 실행 터미널에서 `export OLLAMA_HOST=...`로 지정한다.

### 2.5 CUDA 실제 연산 확인

`torch.cuda.is_available()`뿐 아니라 실제 행렬 연산까지 확인한다.

```bash
python - <<'PY'
import torch

print("torch:", torch.__version__)
print("torch CUDA:", torch.version.cuda)
print("supported arch:", torch.cuda.get_arch_list())
print("CUDA available:", torch.cuda.is_available())
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")

a = torch.randn((1024, 1024), device="cuda")
b = torch.randn((1024, 1024), device="cuda")
c = a @ b
torch.cuda.synchronize()

print("result:", c.mean().item())
print("CUDA operation: SUCCESS")
PY
```

Jetson에서는 실행 중 다른 터미널에서 `sudo tegrastats`의 `GR3D_FREQ`도 확인한다.

## 3. 구조와 재현 조건 검증

| 고정 기준 | 값 |
| --- | --- |
| 실행 커밋 | 실행 시 `manifest.json`의 `executed_commit`에 자동 기록 |
| 그래프 | `routes/test.geojson` |
| 그래프 크기 | 노드 12개, 유향 간선 38개 |
| 그래프 SHA-256 | `9b0ca28cca7c3c55fc795a7a0f8145c3b7f781511567dc92bdb54c0e97d48d68` |
| V1 Direct 프롬프트 SHA-256 | `f71b207f4ccfa32b72de15f0f09ec340ff083768d9ebff6bd29805eff8fdff72` |
| V2 Direct 프롬프트 SHA-256 | `47e58ad5ebe0f5dede1985128bb3055c800ab785a87372ce80ddf2fb25c4660c` |
| V2 CoT 프롬프트 SHA-256 | `b2592acb671b10b493325b9f432fc16ea293a596bd7ae8cd00a72e58cd9c9278` |
| V2 Iterative 프롬프트 SHA-256 | `161bc29b88a67f7d2f5f1a36358fdfaab6721aca1bb102a36e6f191ddfac0eb5` |

장비 비교 전 `git rev-parse HEAD`와 `git status --short`를 확인한다. 두 V2 설정의
`comparison_condition_sha256`이 같으면 Graph, 모델, Start/Target, Ground Truth와
공통 모델 설정이 동일하다는 뜻이다.

구조 검증은 모델을 호출하지 않는다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --check
```

그래프 해시, 노드·간선 수, 코드 최단 경로와 기준값 중 하나라도 다르면 중단한다.
프롬프트나 설정을 바꾸면 설정 파일을 복사하고 `benchmark_id`도 새 값으로 변경한다.

## 4. Ollama 경로 생성 시험

### 4.1 Ollama 설치와 서버 확인

Linux 또는 Jetson에 Ollama가 없다면 설치한다.

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama
sudo systemctl status ollama
ollama --version
curl http://127.0.0.1:11434/api/tags
```

Jetson에서는 동시에 모델 하나와 요청 하나만 처리한다. systemd 서비스를 사용한다면
다음 환경변수를 service override에 설정하고 재시작한다.

```ini
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

systemd 서비스를 사용하지 않을 때만 다음처럼 직접 실행한다.

```bash
OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 ollama serve
```

### 4.2 모델 설치

Jetson 시험은 Ollama 기본 태그 5종을 사용한다.

```bash
ollama pull qwen3:0.6b
ollama pull deepseek-coder:1.3b
ollama pull llama3.2:3b
ollama pull qwen3:4b
ollama pull gemma3:4b

ollama list
```

PC V2는 위 5종에 다음 5종을 추가해 총 10종을 사용한다.

```bash
ollama pull llama3.1:8b
ollama pull mistral-nemo:12b
ollama pull gemma3:12b
ollama pull deepseek-coder:6.7b
ollama pull phi4:14b

ollama list
```

DeepSeek-R1은 `think=false`에서도 최종 JSON 전에 출력 예산을 소진했으므로 V2 대상에서
제외하고, non-thinking 비교군인 `deepseek-coder:1.3b`와
`deepseek-coder:6.7b`를 사용한다. 두 장비에서 같은 태그를 비교할 때는
`ollama list`의 ID가 같은지 확인한다.

원격 Ollama 서버를 사용한다면 벤치마크를 실행할 터미널에서 지정한다.

```bash
export OLLAMA_HOST=http://서버주소:11434
curl "$OLLAMA_HOST/api/tags"
```

### 4.3 고정 설정

| 항목 | PC 10종 선별 | Jetson 5종 / 장비 비교 |
| --- | --- | --- |
| 설정 파일 | `route_generation_benchmark.json` | `route_generation_benchmark_jetson.json` |
| 모델 수 | 10종 | 5종 |
| `num_ctx` | 4096 | 4096 |
| 반복 | 경로별 5회 | 경로별 5회 |
| 예열 | 모델별 1회 | 모델별 1회 |

공통값은 `temperature=0`, `seed=20260928`, `num_ctx=4096`, `num_predict=512`,
요청 제한 120초, 최대 시도 1회, `keep_alive=5m`이다. DeepSeek 비교군은
non-thinking인 `deepseek-coder:1.3b`와 `deepseek-coder:6.7b`를 사용하므로
R1 전용 장문 thinking 예산을 적용하지 않는다. 0.15초는 응답 완료 후 실시간성
충족 여부를 분류하는 기준이며 요청 제한 시간이 아니다.

### 4.4 실행

Jetson:

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --output simulation/benchmark_results/jetson-$(date +%Y%m%d-%H%M%S)
```

PC 10종 선별:

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark.json \
  --output simulation/benchmark_results/pc-$(date +%Y%m%d-%H%M%S)
```

PC와 Jetson의 순수 장비 차이를 비교할 때는 PC에서도 Jetson 설정 파일을 사용한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --output simulation/benchmark_results/pc-matched-$(date +%Y%m%d-%H%M%S)
```

두 설정은 `num_ctx=4096`으로 같지만 모델 수가 다르므로, PC 10종 전체와 Jetson 5종 전체를 직접 비교하지 않고 공통 5종만 장비 비교에 사용한다.

### 4.5 재개와 결과 재추출

중단된 Ollama 시험은 같은 설정과 결과 폴더로 재개한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --resume simulation/benchmark_results/<실행 폴더>
```

모델을 다시 호출하지 않고 `trials.jsonl`에서 요약과 CSV를 재생성한다.

```bash
python -m simulation.evaluation.benchmark \
  --export-results simulation/benchmark_results/<실행 폴더>
```

## 5. Laya 경로 선택 시험

`convaiinnovations/laya-multilingual`이 코드가 만든 후보 중 하나를 선택한다. Ollaya
서버는 사용하지 않고 Hugging Face checkpoint를 PyTorch CUDA로 직접 실행한다.
최단 경로 질문은 `routes/test.geojson`의 실제 좌표와 저장된 Edge `weight`를 사용하며,
V1과 같은 5개 Start/Target 각각에 대해 코드가 만든 유효 경로 후보 5개를 전달한다.
정답 최단 경로는 선택지 1~5번에 한 번씩 배치한다.

### 5.1 설정

`simulation/.env`:

```dotenv
ROUTE_SELECTOR=laya
LAYA_HF_MODEL=convaiinnovations/laya-multilingual
LAYA_DEVICE=cuda:0
LAYA_REQUIRE_CUDA=true
# V1 후보 선택 입력이 잘리지 않도록 PC와 Jetson에서 같은 값 사용
LAYA_MAX_LENGTH=4096
HF_HOME=/home/<사용자명>/.cache/huggingface
# HF_TOKEN=
```

공개 checkpoint에는 일반적으로 `HF_TOKEN`이 필요하지 않다. `LAYA_REQUIRE_CUDA=true`이면
CUDA를 사용할 수 없거나 CPU fallback이 발생했을 때 시험을 실패 처리한다.
`LAYA_MAX_LENGTH`는 글자 수가 아니라 질문 head까지 포함한 토큰 예산이다. Laya가
허용하는 범위는 1~8192이며, V1 재측정에서는 PC와 Jetson 모두 4096으로
고정한다.

### 5.2 V1 후보 선택 반복 측정

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/<환경>-laya-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/<환경>-laya-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1

```

`<환경>`에는 `pc-rtx4070` 또는 `jetson-orin`을 사용한다. 첫 명령은 직관·사고 질문과
실제 맵 5개 최단거리 질문을 한국어와 영어로 시험하고 정답을 다섯 선택지 위치에
옮긴다. 기본 반복 5회 기준 총 350회이며, 이 중 실제 경로 선택은 250회다. 두 번째
명령은 choice·score·noul 질문을 시험한다.

여기서 반복은 동일한 V1 후보 선택 문제를 통계 측정을 위해 5회 실행한다는 뜻이다.
다음 노드를 여러 번 선택해 하나의 경로를 만드는 V2 Iterative 시험과는 다르다.

V1 Laya 재측정 결과는 `selector_latency_trials.jsonl`에 `usage`와
`state_truncated`로 기록된다. 정상 결과라면 요약 파일에서
`state_truncated_count=0`, `state_truncation_unreported_count=0`이고,
`full_input_preserved_count`가 성공한 요청 수와 같아야 한다.
`usage.state_tokens_dropped`가 0보다 크거나 `state_truncated=true`이면 해당 실행은
V1 재측정 결과에서 제외한다.

### 5.3 V1 AllRoutes 전체 경로 선택 시험

기존 V1 시험은 코드가 고른 경로 후보 5개 중 하나를 선택한다. AllRoutes 시험은
각 Start/Target 사이의 **모든 유효 단순 유향 경로**를 생성해 한 번의 선택 문제로
전달한다. 단순 경로는 같은 노드를 두 번 방문하지 않는 경로다.

모델 입력은 다음과 같이 구성한다.

- `state`: Start/Target과 전체 `CompactRouteGraph`
- `criteria`: `path=[0, 3, 4, 6]` 형태의 전체 경로 후보
- 후보에는 거리나 정답 표시를 넣지 않음
- 모델은 CompactRouteGraph의 기존 Edge `weight` 합을 비교해 최단 경로를 선택
- 후보 순서는 언어·경로·반복마다 고정 seed로 섞고 그 seed를 결과에 기록

현재 실제 맵의 후보 수는 다음과 같다.

| Start → Target | 전체 단순 경로 수 |
| --- | ---: |
| 0 → 2 | 24 |
| 3 → 15 | 25 |
| 5 → 18 | 39 |
| 1 → 4 | 63 |
| 6 → 2 | 82 |

Laya는 그래프 입력과 최대 82개의 선택지를 모두 보존해야 하므로 AllRoutes 실행 전에
토큰 예산을 별도로 늘린다.

```bash
export LAYA_MAX_LENGTH=8192
export LAYA_HEAD_MAX_LENGTH=2048
```

`LAYA_MAX_LENGTH`는 전체 입력 예산이고, `LAYA_HEAD_MAX_LENGTH`는 선택지 head가 사용할
수 있는 최대 토큰 수다. 선택지가 잘리면 해당 실행은 유효한 비교 결과로 사용하지 않는다.

Laya 실행:

```bash
ROUTE_SELECTOR=laya \
python -m simulation.evaluation.selector_all_routes_benchmark \
  --output simulation/benchmark_results/<환경>-laya-all-routes-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15
```

Kev 벤치마크 명령만 실행해서는 안 된다. 처음 사용하는 환경에서는 다음 순서가
필수다.

1. [6.1 공통 설치](#61-공통-설치)에 따라 Kev 저장소와 서버 의존성을 설치한다.
2. 터미널 1에서 시험할 모델의 서버를 실행한다.
   - 0.8B: [6.2 Kev-0.8B 서버 실행](#62-kev-08b-서버-실행)
   - 4B: [6.4 Kev-4B 서버 실행](#64-kev-4b-서버-실행)
3. `GET /v1/models`에서 `run`, `device`, `backend`, `dtype`을 확인한다.
4. 서버 터미널을 열어 둔 상태로 터미널 2에서 벤치마크를 실행한다.

아래 예시는 Kev-0.8B 서버가 8011 포트에서 실행 중인 경우다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

ROUTE_SELECTOR=kev \
KEV_HOST=http://127.0.0.1:8011 \
KEV_MODEL=kev-08b \
KEV_REQUIRE_CUDA=true \
python -m simulation.evaluation.selector_all_routes_benchmark \
  --output simulation/benchmark_results/<환경>-kev-08b-all-routes-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15
```

Kev-4B를 시험할 때는 0.8B 서버를 종료하고 4B 서버를 실행한 뒤
`KEV_MODEL=kev-4b`와 결과 폴더 이름을 `kev-4b`로 변경한다. `KEV_MODEL`은 모델을
다운로드하거나 서버에 로드하는 설정이 아니라, 현재 서버의 `--run` checkpoint가
기대한 모델과 일치하는지 검증하고 결과에 모델명을 기록하는 설정이다.

Ollama 실행:

```bash
ROUTE_SELECTOR=ollama OLLAMA_MODEL=qwen3:4b \
python -m simulation.evaluation.selector_all_routes_benchmark \
  --output simulation/benchmark_results/<환경>-qwen3-4b-all-routes-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15
```

결과 폴더에는 다음 파일이 생성된다.

| 파일 | 내용 |
| --- | --- |
| `manifest.json` | 그래프·프롬프트 해시, 후보 수, seed, 모델과 장치 |
| `selector_all_routes_trials.jsonl` | 요청별 후보 순서, 선택 경로, 확률, 시간과 오류 |
| `selector_all_routes_summary.json` | 전체·언어별·경로별 정확도와 지연시간 |
| `selector_all_routes_samples.csv` | 그래프 작성용 행 단위 결과 |

정상 결과는 `error_count=0`이어야 한다. Laya는 추가로
`state_truncated_count=0`, `state_truncation_unreported_count=0`,
`option_completeness_unreported_count=0`, `incomplete_option_trial_count=0`,
Laya와 Kev는
`incomplete_probability_trial_count=0`도 확인한다. Ollama가 선택지별 확률을 반환하지
않는 경우 확률 완전성은 `null`이며 오류가 아니다. 정확도는 후보 수에 따른 무작위
기준선 `1 / candidate_count`와 함께 비교한다.

## 6. Kev 경로 선택 시험

Kev는 코드가 만든 경로 후보 중 하나를 선택하고 각 선택지의 확률을 반환한다.
`KevSelector`는 Kev 서버의 `GET /v1/models`, `POST /v1/systemone` API를
호출한다.

| 시험 모델 | checkpoint | 포트 | 대상 |
| --- | --- | ---: | --- |
| Kev-0.8B | `jaredpalmer/kev-0.8b@v1.0` | 8011 | PC·Jetson 공통 |
| Kev-4B | `jaredpalmer/kev-4b@v1.0` | 8011 | PC 추가 비교 |

> 결과 폴더 이름만으로 모델이 바뀌지는 않는다. 실제 모델은 Kev 서버 실행 명령의
> `--run`으로 결정되며, 벤치마크 전에 `/v1/models`의 `run` 값을 확인한다.
> 두 모델은 같은 8011 포트를 사용하므로 하나의 서버를 종료한 뒤 다른 서버를
> 실행한다. `KEV_MODEL`도 실행한 checkpoint에 맞게 변경해야 한다.

### 6.1 공통 설치

Kev 저장소가 없다면 한 번만 내려받는다.

```bash
test -d ~/kev || git clone https://github.com/jaredpalmer/kev.git ~/kev
```

프로젝트에서 사용하는 Python 가상환경에 Kev 서버 의존성을 설치한다.

```bash
source ~/venv/robot/bin/activate
cd ~/kev

python -m pip install --no-cache-dir -e ".[serve]"
python -m pip check
```

이미 같은 가상환경에서 Kev 서버를 정상 실행했다면 설치를 반복하지 않는다.
CUDA가 준비됐는지 확인한다.

```bash
python - <<'PY'
import torch

print("torch:", torch.__version__)
print("cuda:", torch.cuda.is_available())
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
PY
```

### 6.2 Kev-0.8B 서버 실행

터미널 1에서 실행하고 서버 터미널을 계속 열어 둔다.

```bash
source ~/venv/robot/bin/activate
cd ~/kev

KEV_BACKEND=torch \
KEV_DTYPE=bf16 \
KEV_PREFIX_CACHE=0 \
KEV_CUDA_GRAPHS=0 \
KEV_FUSED=0 \
python -m kev.serve \
  --run jaredpalmer/kev-0.8b@v1.0 \
  --port 8011 \
  2>&1 | tee ~/kev-0.8b-server.log
```

첫 실행에서는 Kev checkpoint와 `Qwen/Qwen3.5-0.8B-Base`가 다운로드된다.
`Application startup complete`가 출력되면 터미널 2에서 확인한다.

```bash
curl -sS http://127.0.0.1:8011/v1/models \
  | python -m json.tool

nvidia-smi
```

다음 값이 나와야 한다.

```text
run: jaredpalmer/kev-0.8b
base: Qwen/Qwen3.5-0.8B-Base
device: cuda
backend: torch
dtype: bfloat16
```

### 6.3 Kev-0.8B 벤치마크 실행

터미널 2에서 실행한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

export ROUTE_SELECTOR=kev
export KEV_HOST=http://127.0.0.1:8011
export KEV_MODEL=kev-08b
export KEV_TIMEOUT_SECONDS=60
export KEV_REQUIRE_CUDA=true

RESULT_DIR="simulation/benchmark_results/pc-rtx4070-kev-0.8b-latency-$(date +%Y%m%d-%H%M%S)"

python -m simulation.evaluation.selector_latency_benchmark \
  --output "$RESULT_DIR" \
  --repeats 5 \
  --warmups 1 \
  --deadline 0.15
```

0.8B의 choice·score·noul question type 벤치마크도 같은 서버 설정으로 실행한다.

```bash
QUESTION_RESULT_DIR="simulation/benchmark_results/pc-rtx4070-kev-0.8b-question-types-$(date +%Y%m%d-%H%M%S)"

python -m simulation.evaluation.selector_question_types_benchmark \
  --output "$QUESTION_RESULT_DIR" \
  --repeats 5 \
  --warmups 1
```

Jetson에서는 출력 폴더 이름만 다음처럼 변경한다.

```bash
RESULT_DIR="simulation/benchmark_results/jetson-orin-kev-0.8b-latency-$(date +%Y%m%d-%H%M%S)"
QUESTION_RESULT_DIR="simulation/benchmark_results/jetson-orin-kev-0.8b-question-types-$(date +%Y%m%d-%H%M%S)"
```

0.8B 시험이 끝나면 터미널 1에서 `Ctrl+C`로 서버를 종료한 뒤 4B 시험을
시작한다. 두 모델 서버를 동시에 실행하면 GPU 메모리가 중복 사용된다.

### 6.4 Kev-4B 서버 실행

Kev-4B는 터미널 1에서 실행한다.

```bash
source ~/venv/robot/bin/activate
cd ~/kev

KEV_BACKEND=torch \
KEV_DTYPE=bf16 \
KEV_PREFIX_CACHE=0 \
KEV_CUDA_GRAPHS=0 \
KEV_FUSED=0 \
python -m kev.serve \
  --run jaredpalmer/kev-4b@v1.0 \
  --port 8011 \
  2>&1 | tee ~/kev-4b-server.log
```

첫 실행에서는 Kev checkpoint와 `Qwen/Qwen3.5-4B-Base`가 다운로드된다.
`Application startup complete`가 출력되면 터미널 2에서 확인한다.

```bash
curl -sS http://127.0.0.1:8011/v1/models \
  | python -m json.tool

nvidia-smi
```

다음 값이 나와야 한다.

```text
run: jaredpalmer/kev-4b
base: Qwen/Qwen3.5-4B-Base
device: cuda
backend: torch
dtype: bfloat16
```

`run`이 0.8B이거나 `device`가 CPU이면 4B 벤치마크를 시작하지 않는다.

### 6.5 Kev-4B 벤치마크 실행

터미널 2에서 실행한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

export ROUTE_SELECTOR=kev
export KEV_HOST=http://127.0.0.1:8011
export KEV_MODEL=kev-4b
export KEV_TIMEOUT_SECONDS=60
export KEV_REQUIRE_CUDA=true

RESULT_DIR="simulation/benchmark_results/pc-rtx4070-kev-4b-latency-$(date +%Y%m%d-%H%M%S)"

python -m simulation.evaluation.selector_latency_benchmark \
  --output "$RESULT_DIR" \
  --repeats 5 \
  --warmups 1 \
  --deadline 0.15
```

4B의 choice·score·noul question type 벤치마크도 같은 서버 설정으로 실행한다.

```bash
QUESTION_RESULT_DIR="simulation/benchmark_results/pc-rtx4070-kev-4b-question-types-$(date +%Y%m%d-%H%M%S)"

python -m simulation.evaluation.selector_question_types_benchmark \
  --output "$QUESTION_RESULT_DIR" \
  --repeats 5 \
  --warmups 1
```

`KEV_MODEL`은 결과 파일에 기록할 모델과 기대 checkpoint를 명시한다. 선택기는
`kev-08b`를 `jaredpalmer/kev-0.8b`, `kev-4b`를 `jaredpalmer/kev-4b`와
대조한다. Kev 서버 요청에는 서버가 제공하는 `kev-latest` API 별칭을 내부적으로
사용한다. 환경변수와 실제 서버의 `run`이 다르면 시험을 시작하지 않는다.

실행 중 GPU 상태는 별도 터미널에서 확인한다.

```bash
watch -n 1 nvidia-smi
```

### 6.6 결과 확인

각 벤치마크를 실행한 터미널에서 latency 결과는 `RESULT_DIR`, question type
결과는 `QUESTION_RESULT_DIR`로 확인한다.

```bash
python -m json.tool "$RESULT_DIR/manifest.json"
python -m json.tool "$RESULT_DIR/selector_latency_summary.json"

python -m json.tool "$QUESTION_RESULT_DIR/manifest.json"
python -m json.tool "$QUESTION_RESULT_DIR/selector_question_type_summary.json"
```

`manifest.json`에서 다음 값을 확인한다.

```text
status: complete
selector_name: kev
requested_model: kev-08b 또는 kev-4b
device.kind: cuda
```

결과 파일은 다음과 같다.

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | 실행 설정, 선택기, 모델과 실제 장치 |
| `selector_latency_trials.jsonl` | 요청별 선택 결과, 확률, 정확도와 시간 |
| `selector_latency_summary.json` | 전체·언어·질문 유형·경로별 집계 |
| `selector_latency_samples.csv` | 그래프 작성과 PC·Jetson 비교용 표 |

결과 폴더 이름과 `/v1/models` 확인 결과를 함께 보관해야 0.8B와 4B 결과를
구분할 수 있다. Kev 모델은 영어 중심이므로 한국어와 영어 정확도를 분리해서
확인한다. CUDA 메모리 부족으로 서버 또는 벤치마크가 종료되면 해당 실행은 성능
결과로 사용하지 않는다.

## 7. 결과 파일과 해석

### 7.1 Ollama

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | Git 상태, 설정·그래프·프롬프트 해시, Ollama 환경과 모델별 CPU/GPU 적재 |
| `warmups.jsonl` | 모델별 예열 결과. 본 집계에서 제외 |
| `trials.jsonl` | 입력, 원시 응답, 재계산 결과와 개별 지표 |
| `summary.json` | 모델별·경로별 집계 |
| `model_summary.csv`, `route_summary.csv` | 모델 및 경로 비교 그래프용 |
| `latency_samples.csv`, `trial_samples.csv` | 지연시간 분포와 개별 실행 분석용 |

정답 판정에는 모델이 보고한 거리를 사용하지 않는다. 반환 경로를 공통
`route_service`로 검증하고 코드가 다시 계산한 거리만 사용한다.

### 7.2 Laya·Kev

| 시험 | 생성 파일 |
| --- | --- |
| latency | `manifest.json`, `selector_latency_trials.jsonl`, `selector_latency_summary.json`, `selector_latency_samples.csv` |
| question types | `manifest.json`, `selector_question_type_trials.jsonl`, `selector_question_type_summary.json`, `selector_question_type_samples.csv` |

- latency 시험만 0.15초 충족률을 계산한다.
- question types 시험에는 `--deadline` 옵션이 없다.
- noul 응답은 현재 `confidence`와 `probabilities`를 별도로 저장하지 않는다.
- selector 시험에는 `--resume`이 없다. 중단되면 새 출력 폴더에서 다시 실행한다.
- 실행 직후 `manifest.json`의 장치는 `unknown`일 수 있으며 첫 추론 후 최종값으로 갱신된다.

두 selector 시험은 현재 OS, JetPack, 전체 Python 패키지 목록을 manifest에 저장하지
않는다. 장비 비교 결과를 보관할 때 다음 정보를 함께 저장한다.

```bash
python --version
python -m pip freeze
uname -a
cat /etc/nv_tegra_release 2>/dev/null || true
```

결과 폴더는 `.gitignore` 대상이다. 공유하거나 장비를 초기화하기 전에 별도로 백업한다.

## 8. 장비 비교 지표

| 구분 | 항목 |
| --- | --- |
| 식별 | 실행 Git 커밋, 설정 해시, `selector_name`, 요청·응답 모델 |
| 장치 | 실제 device, GPU 이름, precision, CPU fallback, 오류 수 |
| 정확도 | 전체, 경로별, 한국어·영어, 질문 유형별 정확도 |
| 시간 | wall·model latency 평균, 중앙값, p95와 0.15초 충족률 |
| 확률 | choice의 confidence와 전체 probabilities |

속도는 중앙값과 p95를 함께 보고 첫 모델 로드 시간은 예열과 분리한다. checkpoint,
입력 길이 또는 `num_ctx`가 다르면 장비 성능 비교와 별도 실험으로 분류한다.

## 9. V1과 V2 경로 생성 실험

### 9.1 구분

V1은 기존 Direct LLM 경로 생성 시험이다. V2는 같은 Graph, 모델, Start/Target,
Ground Truth와 공통 모델 설정으로 다음 6조건을 실행한다.

| V2 조건 | 모델 동작 | 추가 입력 방식 |
| --- | --- | --- |
| `direct_no_rag` | 한 번에 최종 경로 생성 | 전체 Graph |
| `direct_graph_retrieval` | 한 번에 최종 경로 생성 | 검색한 경로 관련 부분 Graph |
| `cot_no_rag` | 한 요청 안에서 단계별 계산 후 경로 생성 | 전체 Graph |
| `cot_graph_retrieval` | 한 요청 안에서 단계별 계산 후 경로 생성 | 검색한 경로 관련 부분 Graph |
| `iterative_full_graph_only` | 전체 Graph와 현재 상태를 보고 다음 Node 하나를 선택해 Target까지 반복 | 전체 Graph만 사용 |
| `iterative_neighbor_context` | 같은 입력에 현재 Node 직접 연결정보를 추가하고 Target까지 반복 | 전체 Graph + 정확 조회한 `available_edges` |

여섯 조건은 하나의 `route_generation_v2_matrix.json`에서 파생된다. 따라서 설정
파일을 여섯 개 복사하지 않고도 조건을 고정할 수 있다. V2는 PC 환경에서만
실행하며 하나의 PC matrix로 조건을 고정한다.


### 9.2 CoT와 Dijkstra의 차이

CoT와 Dijkstra는 같은 개념이 아니다.

- **Dijkstra**는 음수가 아닌 Edge weight에서 최단 경로를 구하는 결정적 알고리즘이다.
- **CoT**는 모델이 중간 계산 단계를 따라가도록 유도하는 추론·프롬프트 방식이다.

이 시험의 CoT 프롬프트가 Dijkstra 순서를 지시하지만, 모델이 그 순서를 정확히
수행한다는 보장은 없다. 그래서 최종 경로와 각 Edge를 코드로 다시 검증한다.
Iterative 조건은 모델에게 Dijkstra의 tentative distance나 relaxation을 계산하게 하지
않는다. 매 호출에서 모델은 전체 Graph, 현재 위치, Target, 방문 경로와 누적 거리를
보고 다음 Node 하나만 선택한다. Python은 상태 저장과 모델이 반환한 Node의 실제
방향성 Edge 존재 여부만 검증하며, `criteria`나 선택 후보를 모델 입력에 만들지 않는다.
모델이 고른 Node를 최단 경로 Node로 대신 수정하지도 않는다.

```text
Start Node
    ↓
모델 API가 다음 Node 하나 선택
    ↓
실제 Edge 검증 후 현재 Node 갱신
    ↓
Target 도착까지 반복
```

직접 연결이 하나인 단계도 같은 입력 형식을 유지하기 위해 모델을 호출한다. 최종적으로
Target 도착 여부, 전체 경로 유효성, Ground Truth 최단 경로·거리 일치율, API 호출
횟수와 총 시간을 비교한다.

### 9.3 Graph Retrieval 정의

입력의 원본은 항상 실제 프론트 Graph의 전체 Node·Edge와 Start/Target이다. V2 모델 입력은
좌표를 제거한 `CompactAdjacencyGraph`이며 경로 비용은 저장된 Edge `weight`만 사용한다.

```json
{
  "type": "CompactAdjacencyGraph",
  "directed": true,
  "nodes": [0, 1],
  "adjacency": {
    "0": [{"to": 1, "weight": 0.352}],
    "1": [{"to": 0, "weight": 0.223}]
  }
}
```

반대 방향 Edge는 별도 항목이며 서로 다른 weight를 그대로 유지한다. Direct·CoT의
Retrieval 적용 조건에서는 LLM 호출 전에 다음 조회를 한 번 수행한다.

1. Start에서 방향성 Edge를 따라 도달 가능한 Node를 구한다.
2. 역방향으로 Target에 도달할 수 있는 Node를 구한다.
3. 두 집합의 교집합과 그 사이 Edge를 조회한다.
4. 각 기준 Node에 대해 인접 Node와 저장된 `weight`만 adjacency에 유지한다.

Retrieval은 최단 경로나 최단 후보를 계산하지 않는다. 따라서 모델 입력에는
`shortest_path`가 없고 다음과 같은 연결 정보만 들어간다.

```json
"1": [
  {"to": 0, "weight": 0.3777115936682494},
  {"to": 2, "weight": 0.41118600261748245}
]
```

현재 Graph는 작고 연결성이 높아 Retrieval 결과가 전체 Graph와 같을 수도 있다.
이 경우 정확도 향상 여부와 함께 입력 표현을 adjacency로 명확히 한 효과를 측정한다.
Retrieval이 Ground Truth Edge를 누락하면 모델 실패와 구분해 기록한다.

Direct·CoT에는 경로 관련 부분 Graph를 만드는 Graph Retrieval 조건이 있다.
Iterative에는 Vector RAG나 부분 Graph Retrieval을 사용하지 않는다. Node ID와 방향성
Edge는 값이 정확히 정의된 구조화 데이터이므로 임베딩 유사도로 찾는 것보다
`adjacency[current_node]`를 조회하는 편이 정확하고 빠르다. 이 조건을
`iterative_neighbor_context`라고 부른다.

매 단계 전체 Graph와 상태는 그대로 보내고, Python이 현재 Node에서 이동 가능한
미방문 Edge를 정확히 조회해 다음 형태로 추가한다.

```json
"available_edges": [
  {"node": 1, "distance": 0.3777115936682494},
  {"node": 18, "distance": 0.428476667276754}
]
```

두 Iterative 조건의 입력 차이는 `available_edges` 유무뿐이다.

```text
iterative_full_graph_only
= 전체 Graph + current + target + visited + accumulated distance

iterative_neighbor_context
= 같은 입력 + adjacency[current_node]에서 정확히 조회한 available_edges
```

Vector RAG는 자연어 장애물 보고, 안전 정책, 운송 규칙, 과거 운행 사례처럼 ID로
정확히 조회하기 어려운 비정형 정보를 의미 유사도로 검색할 때 별도 적용한다.

### 9.4 V2 6조건 실행

Ollama를 호출하지 않고 행렬 구조와 Ground Truth를 먼저 확인한다.

```bash
python -m simulation.evaluation.v2_benchmark \
  --matrix simulation/evaluation/route_generation_v2_matrix.json \
  --check
```

PC 10종 전체를 6조건으로 실행한다.

```bash
python -m simulation.evaluation.v2_benchmark \
  --matrix simulation/evaluation/route_generation_v2_matrix.json \
  --output simulation/benchmark_results/pc-v2-$(date +%Y%m%d-%H%M%S)
```

V2는 Jetson에서 실행하지 않는다. PC 결과만 V2 비교 자료로 사용한다.

### 9.5 결과 확인

V2 최상위 폴더에는 `matrix_manifest.json`, 파생 설정 6개와 조건별 결과 폴더가
생긴다. 각 조건 폴더의 주요 파일은 다음과 같다.

| 파일 | 확인 내용 |
| --- | --- |
| `manifest.json` | Graph·Prompt·공통 조건 해시, 모델별 실제 설정과 장치 |
| `model_summary.csv` | 정확도, 응답시간, API 호출 수, 입출력 토큰 수 |
| `route_summary.csv` | Start/Target별 정확도와 시간 |
| `trials.jsonl` | 최종 경로, raw 진단, retrieval 정보, iterative 단계 |

추가 Retrieval 지표:

| 지표 | 의미 |
| --- | --- |
| `retrieved_node_count` | 모델에 전달된 Node 수 |
| `retrieved_edge_count` | 모델에 전달된 Edge 수 |
| `ground_truth_node_recall` | 정답 경로 Node 포함률 |
| `ground_truth_edge_recall` | 정답 경로 Edge 포함률 |
| `ground_truth_path_available` | Retrieval Graph에 정답 경로 전체가 존재하는지 |

두 조건을 통합 비교한다.

```bash
V2_DIR=simulation/benchmark_results/<pc-v2-결과폴더>

python -m simulation.evaluation.compare_strategy_results \
  --generation DirectNoRAG="$V2_DIR/direct_no_rag" \
  --generation DirectGraphRetrieval="$V2_DIR/direct_graph_retrieval" \
  --generation CoTNoRAG="$V2_DIR/cot_no_rag" \
  --generation CoTGraphRetrieval="$V2_DIR/cot_graph_retrieval" \
  --generation IterativeFullGraph="$V2_DIR/iterative_full_graph_only" \
  --generation IterativeNeighborContext="$V2_DIR/iterative_neighbor_context" \
  --output "$V2_DIR/comparison"
```

비교할 핵심 값은 최단 경로·거리 일치율, 총 응답시간, 실제 입력·출력 토큰,
API 호출 횟수, timeout, 출력 예산 소진율과 Retrieval coverage다.

### 9.6 Ollama·Laya·Kev 공통 다음 노드 반복 선택

모델 종류가 달라도 같은 선택 작업으로 비교할 때 사용한다. 모든 모델은 동일한
`CompactAdjacencyGraph`, 현재 Node, 목표 Node, 방문 Node와 누적 거리를 받는다.

- 기본값은 `--candidate-scope neighbors --context-mode neighbor_context`다.
- `neighbors`에서는 `available_edges`를 정확 조회하고, 그 안의 Node만 Laya·Kev·Ollama의 `criteria`로 제공한다.
- 이미 지나온 Node도 실제 outgoing Edge로 연결되어 있으면 `available_edges`와 `criteria`에 다시 포함한다.
- 재방문은 실패로 중단하지 않고 `revisited=true`와 `revisit_count`로 기록한 뒤 Target 도착까지 계속한다.
- 무한 순환은 `--max-steps`에서 중단한다. 기본값은 전체 Node 수의 2배이며 현재 맵에서는 24회다.
- 전체 `CompactAdjacencyGraph`는 후보 Node에서 Target까지의 남은 경로 비용을 판단할 수 있도록 계속 제공한다.
- `--candidate-scope all`: 현재 Node를 제외한 전체 Node를 후보로 제공하며 없는 Edge 선택도 실패로 기록하는 능력 시험이다.
- `--context-mode full_graph_only`: 전체 Graph와 현재 상태만 전달한다.
- `--context-mode neighbor_context`: 동일한 입력에 현재 Node의 미방문 outgoing Edge와 weight를 `available_edges`로 추가한다.
- Context 효과를 비교할 때는 두 실행의 `--candidate-scope`를 동일하게 유지한다.
- 후보가 1개면 모델을 호출하지 않고 유일한 Edge로 이동하며 `forced_step=true`로 기록한다.
  이 단계는 API 호출 수, 모델 단계 지연시간과 0.15초 충족률의 분모에서 제외한다.

```bash
# Context 미적용
ROUTE_SELECTOR=laya \
python -m simulation.evaluation.selector_iterative_route_benchmark \
  --candidate-scope all \
  --context-mode full_graph_only \
  --output simulation/benchmark_results/<환경>-laya-full-graph-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

# 정확 인접 Context 적용: 위 실행과 criteria는 동일
ROUTE_SELECTOR=laya \
python -m simulation.evaluation.selector_iterative_route_benchmark \
  --candidate-scope all \
  --context-mode neighbor_context \
  --output simulation/benchmark_results/<환경>-laya-neighbor-context-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15
```

`ROUTE_SELECTOR`를 `kev` 또는 `ollama`로 바꾸면 같은 입력과 검증 규칙으로 실행한다.
Kev는 0.8B와 4B를 각각 측정한다. 두 checkpoint는 같은 8011 포트를 사용하므로 서버를
동시에 실행하지 않고, 한 모델의 시험이 끝난 뒤 서버를 종료하고 다음 모델을 실행한다.

```bash
# Kev-0.8B 서버가 실행 중일 때
ROUTE_SELECTOR=kev \
KEV_HOST=http://127.0.0.1:8011 \
KEV_MODEL=kev-08b \
python -m simulation.evaluation.selector_iterative_route_benchmark \
  --output simulation/benchmark_results/<환경>-kev-08b-iterative-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

# 0.8B 서버를 종료하고 Kev-4B 서버를 실행한 뒤 측정
ROUTE_SELECTOR=kev \
KEV_HOST=http://127.0.0.1:8011 \
KEV_MODEL=kev-4b \
python -m simulation.evaluation.selector_iterative_route_benchmark \
  --output simulation/benchmark_results/<환경>-kev-4b-iterative-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15 \
  --max-steps 24
```

두 명령은 기본값인 `candidate_scope=neighbors`, `context_mode=neighbor_context`를 사용한다.
`--max-steps`를 생략해도 현재 12개 Node 맵에서는 기본값 24가 적용된다.
따라서 0.8B와 4B 모두 전체 Graph와 현재 상태를 받되, `available_edges` 안의 Node만
choice 후보로 받는다. `requested_model`과 결과 폴더가 다르므로 결과를 서로 구분할 수 있다.

Ollama는 `OLLAMA_MODEL`을 지정한다. 결과에는 실패 단계, 단계별 후보·선택·확률·입력
사용량·응답시간, 재방문, 목표 도착 여부, 최단 경로·거리 일치와 무작위 기준선을 기록한다.
