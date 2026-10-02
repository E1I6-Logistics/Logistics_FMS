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

PC의 10종 목록과 모델 선정 근거는 참고 문서에 정리한다. 두 장비에서 같은 태그를
비교할 때는 `ollama list`의 ID가 같은지 확인한다.

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
LAYA_MAX_LENGTH=1024
HF_HOME=/home/<사용자명>/.cache/huggingface
# HF_TOKEN=
```

공개 checkpoint에는 일반적으로 `HF_TOKEN`이 필요하지 않다. `LAYA_REQUIRE_CUDA=true`이면
CUDA를 사용할 수 없거나 CPU fallback이 발생했을 때 시험을 실패 처리한다.

### 5.2 smoke test

첫 실행은 checkpoint를 다운로드하므로 이후보다 오래 걸린다.

```bash
python - <<'PY'
import json
from pathlib import Path

from simulation.route_selector import get_selector
from simulation.services.route_service import (
    build_compact_route_graph,
    build_route_inputs,
    plan_route,
    validate_and_calculate_path_distance,
)

graph_path = Path("routes/test.geojson")
graph = json.loads(graph_path.read_text(encoding="utf-8"))
points, edges = build_route_inputs(graph, require_stored_weight=True)
shortest = plan_route("0", "2", graph, require_stored_weight=True)
shortest_path = [int(node) for node in shortest["node_ids"]]
_, shortest_distance = validate_and_calculate_path_distance(
    points, edges, shortest_path, 0, 2
)

state = {
    "start_node": 0,
    "target_node": 2,
    "route_graph": build_compact_route_graph(
        graph, graph_path.name, require_stored_weight=True
    ),
}
candidates = {
    "route_a": "path=[0,18,17,2], distance=1.436310720336",
    "route_b": f"path={shortest_path}, distance={shortest_distance:.12f}",
}

selector = get_selector()
try:
    result = selector.select_route(
        state,
        candidates,
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

`runtime.device`는 `cuda` 또는 `cuda:0`처럼 `cuda`로 시작해야 한다. 실행 중
`sudo tegrastats` 또는 `nvidia-smi`에서 GPU 사용도 확인한다.

### 5.3 반복 벤치마크

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

## 6. Kev 경로 선택 시험

`jaredpalmer/kev-0.8b@v1.0`와 `jaredpalmer/kev-4b@v1.0`는 `choice`, `score`,
`noul` 질문에 확률을 반환한다. Jetson과 PC 공통 비교에는 0.8B, RTX 4070 SUPER
PC의 추가 성능 비교에는 4B를 사용한다.
`KevSelector`는 Kev 서버의 `GET /v1/models`, `POST /v1/systemone` API를 호출한다.

### 6.1 설치

Kev 저장소는 프로젝트 밖 `~/kev`에 둔다. 이미 존재한다면 `git clone`을 반복하지
말고 해당 디렉터리에서 상태와 커밋을 확인한다.

```bash
git clone https://github.com/jaredpalmer/kev.git ~/kev
cd ~/kev
git rev-parse HEAD
source ~/venv/robot/bin/activate

python -m pip install --no-cache-dir -e ".[serve]"
python -m pip install --no-cache-dir cffi
python -m pip install --no-cache-dir --upgrade pandas
python -m pip check
```

재현 결과에는 `~/kev`의 커밋도 함께 기록한다. Kev 설치가 NumPy, pandas,
scikit-learn, Transformers를 변경할 수 있으므로 import 위치를 확인한다.

```bash
python - <<'PY'
import numpy
import pandas
import sklearn
import transformers
import torch
import laya
import kev

print("torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("laya:", getattr(laya, "__version__", "unknown"))
print("kev:", getattr(kev, "__version__", "unknown"))
print("numpy:", numpy.__version__)
print("pandas:", pandas.__version__, pandas.__file__)
print("sklearn:", sklearn.__version__)
print("transformers:", transformers.__version__)
PY
```

`pandas.__file__`은 `~/venv/robot` 아래여야 한다.

### 6.2 서버 실행과 확인

```bash
cd ~/kev
source ~/venv/robot/bin/activate

KEV_BACKEND=torch KEV_DTYPE=bf16 KEV_PREFIX_CACHE=0 \
KEV_CUDA_GRAPHS=0 KEV_FUSED=0 \
python -m kev.serve --run jaredpalmer/kev-0.8b@v1.0 --port 8009 \
  2>&1 | tee ~/kev-0.8b-server.log
```

서버 터미널은 계속 실행해 둔다. 다른 터미널에서 확인한다.

```bash
curl -s http://127.0.0.1:8009/v1/models | python -m json.tool
```

응답의 `device`는 `cuda` 또는 `cuda:0`, `run`은 `jaredpalmer/kev-0.8b`여야 한다.

RTX 4070 SUPER PC에서 Kev-4B를 시험할 때는 0.8B 서버를 종료한 뒤 다음처럼
별도 포트로 실행한다. 첫 실행에서 checkpoint가 다운로드된다.

```bash
cd ~/kev
source ~/venv/robot/bin/activate

KEV_BACKEND=torch KEV_DTYPE=bf16 KEV_PREFIX_CACHE=0 \
KEV_CUDA_GRAPHS=0 KEV_FUSED=0 \
python -m kev.serve --run jaredpalmer/kev-4b@v1.0 --port 8010 \
  2>&1 | tee ~/kev-4b-server.log
```

다른 터미널에서 실제 checkpoint와 GPU 사용을 확인한다.

```bash
curl -s http://127.0.0.1:8010/v1/models | python -m json.tool
nvidia-smi
```

### 6.3 FMS 설정과 반복 벤치마크

`simulation/.env`:

```dotenv
ROUTE_SELECTOR=kev
KEV_HOST=http://127.0.0.1:8009
KEV_MODEL=kev-latest
KEV_TIMEOUT_SECONDS=60
KEV_REQUIRE_CUDA=true
# KEV_API_KEY=
```

`KEV_MODEL=kev-latest`는 API 별칭이고 실제 checkpoint는 Kev 서버의 `--run`이
선택한다.

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/<환경>-kev-0.8b-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/<환경>-kev-0.8b-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1
```

PC Kev-4B는 `simulation/.env`의 `KEV_HOST`를 8010으로 바꾼 뒤 실행한다.

```dotenv
ROUTE_SELECTOR=kev
KEV_HOST=http://127.0.0.1:8010
KEV_MODEL=kev-latest
KEV_REQUIRE_CUDA=true
```

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/pc-rtx4070-kev-4b-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15
```

출력 폴더 이름만으로 선택기가 바뀌지 않는다. 결과의 `manifest.json`에서
`selector_name`이 `kev`인지 확인한다.

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

| V2 조건 | 모델 동작 | Graph Retrieval |
| --- | --- | --- |
| `direct_no_rag` | 한 번에 최종 경로 생성 | 미적용 |
| `direct_rag` | 한 번에 최종 경로 생성 | 적용 |
| `cot_no_rag` | 한 요청 안에서 단계별 계산 후 경로 생성 | 미적용 |
| `cot_rag` | 한 요청 안에서 단계별 계산 후 경로 생성 | 적용 |
| `iterative_no_rag` | 모델 API를 여러 번 호출해 탐색 상태 연결 | 미적용 |
| `iterative_rag` | Retrieval Graph로 모델 API를 여러 번 호출 | 적용 |

여섯 조건은 하나의 `route_generation_v2_matrix.json`에서 파생된다. 따라서 설정
파일을 여섯 개 복사하지 않고도 조건을 고정할 수 있다. PC와 Jetson의 모델 목록이
다르기 때문에 장비별 matrix 파일만 분리한다.

### 9.2 CoT와 Dijkstra의 차이

CoT와 Dijkstra는 같은 개념이 아니다.

- **Dijkstra**는 음수가 아닌 Edge weight에서 최단 경로를 구하는 결정적 알고리즘이다.
- **CoT**는 모델이 중간 계산 단계를 따라가도록 유도하는 추론·프롬프트 방식이다.

이 시험의 CoT 프롬프트가 Dijkstra 순서를 지시하지만, 모델이 그 순서를 정확히
수행한다는 보장은 없다. 그래서 최종 경로와 각 Edge를 코드로 다시 검증한다.
Iterative 조건에서는 모델이 매 호출마다 최소 tentative distance Node와 relaxation을
선택한다. Python은 상태 저장과 검증만 하며 잘못된 선택을 대신 수정하지 않는다.

### 9.3 Graph Retrieval 정의

입력의 원본은 항상 실제 프론트 Graph 전체 좌표·Edge와 Start/Target이다. 모델 입력에는
`node_coordinates`도 포함하지만 경로 비용은 저장된 Edge `weight`만 사용한다. Retrieval 적용
조건에서는 LLM 호출 전에 다음 조회를 한 번 수행한다.

1. Start에서 방향성 Edge를 따라 도달 가능한 Node를 구한다.
2. 역방향으로 Target에 도달할 수 있는 Node를 구한다.
3. 두 집합의 교집합과 그 사이 Edge를 조회한다.
4. 각 기준 Node에 대해 인접 Node와 저장된 `weight`를 adjacency로 만든다.

Retrieval은 최단 경로나 최단 후보를 계산하지 않는다. 따라서 모델 입력에는
`shortest_path`가 없고 다음과 같은 연결 정보만 들어간다.

```json
{
  "node": 1,
  "neighbors": [
    {"node": 0, "distance": 0.3777115936682494},
    {"node": 2, "distance": 0.41118600261748245}
  ]
}
```

현재 Graph는 작고 연결성이 높아 Retrieval 결과가 전체 Graph와 같을 수도 있다.
이 경우 정확도 향상 여부와 함께 입력 표현을 adjacency로 명확히 한 효과를 측정한다.
Retrieval이 Ground Truth Edge를 누락하면 모델 실패와 구분해 기록한다.

### 9.4 V1 DeepSeek non-thinking 비교군 실행

DeepSeek-R1은 현재 시험 환경에서 `think=false`가 기대대로 적용되지 않고 출력
예산을 모두 사용한 뒤 최종 JSON 없이 종료됐다. 실시간 경로 생성 비교에서는
R1 대신 `<think>` 출력을 전제로 하지 않는 DeepSeek Coder를 사용한다.

| 장비 | 모델 | Ollama 용량 | 비교 목적 |
| --- | --- | ---: | --- |
| Jetson·PC | `deepseek-coder:1.3b` | 약 776MB | 임베디드 환경의 경량·저지연 비교 |
| PC | `deepseek-coder:6.7b` | 약 3.8GB | 8~12GB VRAM PC의 정확도·속도 비교 |

두 모델은 코드와 자연어를 함께 학습한 코드 특화 모델이다. 따라서 일반 범용
DeepSeek 모델과 동일한 계열 성능으로 해석하지 않고, 그래프 JSON 이해와 경로
출력 형식 준수 능력을 검증하는 별도 비교군으로 기록한다. 두 모델 모두 공통
`num_ctx=4096`, `num_predict=512`, timeout 120초를 사용한다.

모델을 설치한다.

```bash
# Jetson과 PC 공통
ollama pull deepseek-coder:1.3b

# PC 추가
ollama pull deepseek-coder:6.7b
```

설정만 확인한다. Ollama에는 요청하지 않는다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark.json \
  --check
```

Jetson 또는 PC에서 1.3B만 실행한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --model deepseek-coder:1.3b \
  --output simulation/benchmark_results/v1-deepseek-coder-1.3b-$(date +%Y%m%d-%H%M%S)
```

PC에서 6.7B를 실행한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark.json \
  --model deepseek-coder:6.7b \
  --output simulation/benchmark_results/v1-deepseek-coder-6.7b-$(date +%Y%m%d-%H%M%S)
```

### 9.5 V2 6조건 실행

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

Jetson 5종을 실행한다.

```bash
python -m simulation.evaluation.v2_benchmark \
  --matrix simulation/evaluation/route_generation_v2_matrix_jetson.json \
  --output simulation/benchmark_results/jetson-v2-$(date +%Y%m%d-%H%M%S)
```

한 조건 또는 한 모델만 먼저 실행할 수 있다.

```bash
python -m simulation.evaluation.v2_benchmark \
  --matrix simulation/evaluation/route_generation_v2_matrix.json \
  --only cot_rag \
  --model qwen3:0.6b \
  --output simulation/benchmark_results/v2-cot-rag-smoke-$(date +%Y%m%d-%H%M%S)
```

### 9.6 결과 확인

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
  --generation DirectRAG="$V2_DIR/direct_rag" \
  --generation CoTNoRAG="$V2_DIR/cot_no_rag" \
  --generation CoTRAG="$V2_DIR/cot_rag" \
  --generation IterativeNoRAG="$V2_DIR/iterative_no_rag" \
  --generation IterativeRAG="$V2_DIR/iterative_rag" \
  --output "$V2_DIR/comparison"
```

비교할 핵심 값은 최단 경로·거리 일치율, 총 응답시간, 실제 입력·출력 토큰,
API 호출 횟수, timeout, 출력 예산 소진율과 Retrieval coverage다.
