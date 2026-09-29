# Kev와 Laya 비교

## 공통점

Kev와 Laya는 모두 문장을 생성하는 LLM이 아니라, 상태와 질문을 받아 정해진
후보를 판단하는 decision model이다. 두 모델 모두 `choice`, `score`, `noul`
질문을 처리하고 후보별 확률과 신뢰도를 반환한다. 이 프로젝트에서는 경로를
직접 계산하지 않고 코드가 만든 경로 후보 중 하나를 선택하는 역할을 맡는다.

## 차이점

| 구분 | Laya Multilingual | Kev-0.8B |
| --- | --- | --- |
| 주 용도 | 다국어 typed decision | 영어 typed decision |
| 기반 구조 | mmBERT encoder | Qwen3.5-0.8B Base |
| 파라미터 | 약 322M | 약 0.8B |
| 체크포인트 | 완성된 decision checkpoint | PEFT LoRA adapter + pointer head |
| 실행 방식 | `laya.load()`로 직접 로드 | 공식 Kev runtime으로 base·adapter·head 결합 |
| 한국어 | 지원 | 영어 중심 |
| GPU 메모리 | 상대적으로 작음 | 공식 기준 약 4GB급 |
| Jetson 적용 | 기본 후보 | 메모리 여유 확인 후 비교 후보 |

## 모델 구조

Laya는 Hugging Face checkpoint 안에 encoder, decision head, tokenizer와 확률
보정 설정이 함께 들어 있다. 따라서 한 checkpoint를 직접 로드할 수 있다.

```text
state + question + options
          ↓
    mmBERT encoder
          ↓
   Laya decision head
          ↓
 choice / score / noul
```

Kev는 Hugging Face PEFT adapter만으로 완성되지 않는다. Qwen 기본 모델,
LoRA adapter, Kev 전용 `head.pt`, 입력 렌더링과 temperature 보정을 공식
runtime이 결합해야 한다.

```text
Qwen3.5 Base
    + PEFT LoRA adapter
    + Kev pointer head
    + Kev input rendering
    + temperature calibration
              ↓
      choice / score / noul
```

일반 `PeftModel.from_pretrained()`만 호출하면 LoRA는 적용되지만 pointer head와
Kev 전용 후처리가 빠지므로 동일한 결과를 만들 수 없다.

## 프로젝트 구현

```text
simulation/route_selector/
├── laya_selector.py
├── kev_selector.py
└── registry.py
```

- `laya_selector.py`: Hugging Face Laya checkpoint를 Python 프로세스의 CUDA에 직접 로드
- `kev_selector.py`: 공식 Kev runtime 서버의 TypeSafe 호환 API 호출
- `registry.py`: `ROUTE_SELECTOR=laya` 또는 `kev`로 구현 선택

Laya 설정:

```dotenv
ROUTE_SELECTOR=laya
LAYA_HF_MODEL=convaiinnovations/laya-multilingual
LAYA_DEVICE=cuda:0
LAYA_REQUIRE_CUDA=true
LAYA_MAX_LENGTH=1024
```

Kev 설정:

```dotenv
ROUTE_SELECTOR=kev
KEV_HOST=http://127.0.0.1:8009
KEV_MODEL=kev-latest
KEV_REQUIRE_CUDA=true
KEV_TIMEOUT_SECONDS=60
```

## Jetson Orin Nano 적용 기준

Jetson Orin Nano의 가용 RAM이 약 4.5GB이므로 Laya와 Kev를 동시에 메모리에
올리지 않는다. 기본 모델은 한국어를 지원하고 더 작은 Laya Multilingual로
두고, Kev는 `kev-0.8b`만 영어 비교 시험에 사용한다. Kev-4B 이상은 메모리
요구량 때문에 제외한다.

Kev는 PEFT 방식이지만 추론할 때 Qwen 기본 모델 전체가 필요하다. adapter
파일이 작다는 이유로 추론 메모리도 작아지는 것은 아니다. Kev 실행 전 다른
GPU 모델을 내리고, 짧은 입력과 요청 한 개부터 smoke test를 진행한다.

## 선택 기준

- 한국어 또는 다국어 입력: Laya Multilingual
- 더 낮은 메모리 사용량이 필요한 경우: Laya Multilingual
- 영어 입력에서 PEFT decision model을 비교하는 경우: Kev-0.8B
- 경로 자체 생성: 두 모델의 역할이 아니며 기존 경로 계산 코드 또는 생성형 LLM 사용
