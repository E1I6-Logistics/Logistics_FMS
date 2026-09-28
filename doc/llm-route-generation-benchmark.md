# Ollama 최단 경로 생성 반복 테스트

이 문서는 코드로 계산한 최단 경로와 Ollama 로컬 모델이 생성한 경로를
같은 조건에서 반복 비교하는 방법을 설명한다. 이 실행기는 로봇 이동 명령을
보내지 않으며 FastAPI, ROS 2, Zenoh, 데이터베이스를 사용하지 않는다.

## 1. 재현 기준

설정 파일은 `simulation/evaluation/route_generation_benchmark.json`이다. 2026-09-28에
진행한 2차 테스트 조건을 다음과 같이 고정한다.

| 항목 | 값 |
| --- | --- |
| 기준 커밋 | `1e7535c9e276a1a5e0ab3ba9770c56e4bb0f68fc` |
| 그래프 | `routes/test_benchmark_v1.geojson` |
| 그래프 SHA-256 | `00e1f02cce0f5007342dfef4c7c1a0d95f36eb639c530dcf0c8e7c7ce0f304c3` |
| 프롬프트 SHA-256 | `53276490f7224be85126a1576d519d132566193b9bd7fec7d32b4e38f4cbfe44` |
| 그래프 크기 | 노드 14개, 유향 간선 28개 |
| 모델 | `qwen3:0.6b`, `qwen3:1.7b`, `gemma3:1b`, `qwen3:4b`, `deepseek-r1:14b` |
| 경로 | `0→6`, `1→12`, `2→10` |
| 반복 | 모델·경로 조합별 3회 |
| 예열 | 모델별 1회, 본 시험 집계에서 제외 |
| 생성 설정 | `temperature=0`, `seed=20260928`, `num_ctx=4096`, `num_predict=512` |
| 추론 모드 | qwen3 모델은 `think=false`, gemma3에는 `think`를 전달하지 않음 |
| 제한 시간 | 요청당 120초 |
| 최대 시도 | 1회 |
| 모델 유지 | `keep_alive=5m` |
| 실시간 판단 기준 | 0.15초 |

0.15초는 요청 제한 시간이 아니다. `timeout_seconds=120`은 응답을 기다리는
최대 시간이고, `realtime_deadline_seconds=0.15`는 응답 완료 후 실시간 기준을
충족했는지 분류하는 값이다.

설정 파일에는 기준 경로와 거리도 함께 저장한다. 실행 전 코드가 다시 계산한
경로·거리, 그래프 개수, 그래프 SHA-256 중 하나라도 기준과 다르면 테스트를
중단한다. 따라서 그래프나 최단 경로 코드가 달라진 상태에서 이전 실험과 같은
이름으로 결과를 만드는 것을 방지한다.

## 2. LLM 프롬프트

실제로 사용하는 영문 프롬프트 전문은
`simulation/evaluation/route_generation_benchmark.json`의 `prompt`에 저장한다. 핵심 규칙은
다음과 같다.

- 입력은 시작 노드, 도착 노드, CompactRouteGraph이다.
- 간선은 `from`에서 `to` 방향으로만 이동한다.
- 간선의 `weight`를 그대로 사용한다.
- Dijkstra 알고리즘으로 총가중치가 가장 작은 경로를 찾는다.
- 시작·도착 노드와 모든 연속 간선의 유효성을 확인한다.
- JSON Schema에 맞는 객체만 반환한다.

실행 결과의 `manifest.json`에는 프롬프트 SHA-256을 기록한다. 프롬프트를
변경하여 실험할 경우 기존 결과 폴더를 재사용하지 말고 설정 파일과
`benchmark_id`를 새 버전으로 만든다.

## 3. 실행 전 구조 검증

원격 컴퓨터의 WSL 터미널에서 실행한다.

```bash
cd ~/Logistics_FMS
git branch --show-current
source ~/venv/robot/bin/activate
python -m pip install -r simulation/requirements.txt
python -m simulation.evaluation.benchmark --check
```

`--check`는 Ollama에 요청하지 않는다. 그래프 해시, 노드·간선 개수,
코드 최단 경로와 기준값만 확인한다.

Ollama 없이 전체 반복·저장·집계·재개 구조를 확인하려면 Mock 테스트를 실행한다.

```bash
python -m unittest tests.test_route_generation_benchmark -v
python -m unittest tests.test_ollama_provider -v
```

Mock 테스트는 모델 성능을 평가하지 않는다. 5개 모델 × 3개 경로 × 3회인
45개 본 시험과 모델별 예열 5개가 분리되는지, CSV가 생성되는지, 완료된
결과를 재실행하지 않는지만 빠르게 확인한다.

## 4. Ollama 및 모델 준비

Ollama 서버와 설치된 모델을 확인한다.

```bash
ollama --version
ollama list
curl http://127.0.0.1:11434/api/tags
```

서버가 동작하지 않으면 별도 터미널에서 실행한다.

```bash
ollama serve
```

누락된 모델만 내려받는다.

```bash
ollama pull qwen3:0.6b
ollama pull qwen3:1.7b
ollama pull gemma3:1b
ollama pull qwen3:4b
ollama pull deepseek-r1:14b
```

다른 컴퓨터의 Ollama 서버를 사용하면 실행 전에 주소를 지정한다.

```bash
export OLLAMA_HOST=http://서버주소:11434
```

## 5. Jetson 또는 원격 컴퓨터에서 본 시험 실행

결과 폴더 이름에는 장비와 실행 시각을 넣는 것을 권장한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.benchmark \
  --output simulation/benchmark_results/jetson-$(date +%Y%m%d-%H%M%S)
```

실행기는 모델별 예열을 먼저 수행하고 다음으로 각 경로를 3회 실행한다.
터미널에는 모델, 경로, 반복 번호, 유효 경로 여부, 최단 거리 일치 여부,
응답 시간이 한 줄씩 출력된다.

실행이 중단되면 같은 폴더를 `--resume`에 전달한다.

```bash
python -m simulation.evaluation.benchmark \
  --resume simulation/benchmark_results/jetson-실행시각
```

이미 기록된 예열과 `모델·시작·도착·반복 번호` 조합은 다시 요청하지 않는다.
설정 파일 또는 그래프 해시가 원래 실행과 다르면 재개를 거부한다.

## 6. 생성되는 파일

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | Git 상태, 장비, Ollama 버전, 모델 정보, 그래프·프롬프트·설정 해시 |
| `warmups.jsonl` | 모델별 예열 응답과 시간. 정확도·지연시간 집계에서는 제외 |
| `trials.jsonl` | 본 시험의 입력, 원시 추론 정보, 응답, 재계산 결과, 모든 지표 |
| `summary.json` | 모델별·경로별 집계 결과 |
| `model_summary.csv` | 모델 간 정확도와 지연시간 그래프 작성용 |
| `route_summary.csv` | 모델·경로별 난이도 비교 그래프 작성용 |
| `latency_samples.csv` | 모든 개별 실행의 지연시간 분포 그래프 작성용 |

CSV는 Excel에서 한글이 깨지지 않도록 UTF-8 BOM 형식으로 저장한다.
실행 결과 폴더는 `.gitignore`에 포함되므로 결과를 공유할 때는 별도 보관한다.

## 7. 기록 지표

각 본 시험에서 다음 값을 기록한다.

- JSON 객체 파싱 성공 여부
- 방향성 간선으로 연결된 유효 경로 여부
- 기준 최단 경로와 노드 배열이 같은지
- 코드가 재계산한 최단 거리와 같은지
- 절대 거리 오차
- 모델 보고 거리와 코드 재계산 거리의 오차
- 전체 응답 시간
- 0.15초 실시간 기준 충족 여부
- 제한 시간 초과 여부
- 최초 시도 성공 및 재시도 성공 여부
- 입력 문자 수와 추정 토큰 수
- Ollama 원시 요청·응답, 종료 이유 및 제공되는 토큰 수

정답 판정에는 모델이 보고한 거리를 사용하지 않는다. 모델이 반환한 경로를
공통 `route_service`로 다시 검증하고 계산한 거리만 사용한다.

## 8. 재현성의 범위

고정된 그래프·프롬프트·모델 digest·파라미터·seed를 사용하면 논리적인 시험
조건을 재현할 수 있다. 응답 시간은 장비, Ollama 버전, 드라이버, 발열 및
다른 프로세스의 부하에 따라 달라지므로 이전 컴퓨터와 동일한 숫자가 나오는
것을 보장하지 않는다. 이 차이를 비교할 수 있도록 장비와 런타임 정보가
`manifest.json`에 저장된다.
