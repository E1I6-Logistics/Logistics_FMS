"""
[플러그인 레지스트리] LLM_PROVIDER 환경변수 값에 따라 알맞은
Provider 인스턴스를 만들어 반환한다.

사용 예:
    cp simulation/.env.example simulation/.env
    # simulation/.env에서 LLM_PROVIDER, 모델, API 키를 설정한다.
    # LLM_PROVIDER가 설정된 별도 Mock Fleet을 실행하고 Zenoh goal을 보내야
    # 비교가 실행된다. --robot-number/--point-id CLI는 FMS API 명령만 보낸다.
    python simulation/mock_fleet.py

새 벤더(예: Google Gemini)를 추가하려면:
    1. base.LLMPathProvider를 상속한 새 클래스를 만들고
    2. 아래 _PROVIDERS 딕셔너리에 한 줄만 추가하면 된다.
   → llm_route_comparison.py 등 호출부는 전혀 수정할 필요 없음.
"""

import os
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv

from .base import LLMPathProvider


# 두 진입점(mock_fleet, run_llm_comparison)이 registry를 import한다.
# 이 시점에 한 번 로드해야 Mock Fleet의 LLM_PROVIDER 활성화 검사에도 반영된다.
# 이미 셸에 설정된 값은 덮어쓰지 않는다.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


# 선택한 provider 모듈만 import하기 위한 지연 로딩 정보다.
# 이렇게 해야 OpenAI만 사용할 때 anthropic/ollama 패키지가 없어도 실행된다.
_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": (".openai_provider", "OpenAIPathProvider"),
    "anthropic": (".anthropic_provider", "AnthropicPathProvider"),
    "ollama": (".ollama_provider", "OllamaPathProvider"),
}


def get_provider() -> LLMPathProvider:
    """선택된 LLM 구현을 생성한다. API 자격 증명은 해당 구현에서 확인한다."""
    provider_key = os.getenv("LLM_PROVIDER", "openai").strip().lower()

    if provider_key not in _PROVIDERS:
        available = ", ".join(sorted(_PROVIDERS))
        raise RuntimeError(
            f"알 수 없는 LLM_PROVIDER: '{provider_key}' (사용 가능: {available})"
        )

    # 선택된 provider의 SDK와 구현만 이 시점에 불러온다.
    module_name, class_name = _PROVIDERS[provider_key]
    provider_module = import_module(module_name, package=__package__)
    provider_class = getattr(provider_module, class_name)

    return provider_class()
