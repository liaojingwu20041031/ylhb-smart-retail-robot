from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class HealthInputs:
    now: float
    required_nodes: Dict[str, bool] = field(default_factory=dict)
    b1_service_ready: bool = False
    chassis_status: str = ''
    chassis_received_at: float = 0.0
    chassis_status_max_age_sec: float = 2.5
    voice_session_enabled: bool = False
    voice_session_service_ready: bool = False
    capture_voice_enabled: bool = False
    capture_voice_service_ready: bool = False
    tts_enabled: bool = False
    voice_output_present: bool = False
    dashscope_api_key_present: bool = False
    tts_speaking: bool = False
    last_voice_event_at: float = 0.0


@dataclass(frozen=True)
class HealthResult:
    ready: bool
    reasons: List[str]
    capabilities: Dict[str, str]


def evaluate_health(inputs: HealthInputs) -> HealthResult:
    reasons: List[str] = []
    capabilities: Dict[str, str] = {}

    for node_name, present in inputs.required_nodes.items():
        capabilities[node_name] = 'online' if present else 'missing'
        if not present:
            reasons.append(f'关键节点缺失: {node_name}')

    capabilities['b1_service'] = 'ready' if inputs.b1_service_ready else 'missing'
    if not inputs.b1_service_ready:
        reasons.append('B1 服务未就绪')

    chassis_age = (
        inputs.now - inputs.chassis_received_at
        if inputs.chassis_received_at > 0.0 else float('inf')
    )
    chassis_state = inputs.chassis_status.split(maxsplit=1)[0] if inputs.chassis_status else ''
    chassis_online = (
        chassis_state == 'online'
        and chassis_age <= inputs.chassis_status_max_age_sec
    )
    capabilities['chassis'] = chassis_state or 'missing'
    if not inputs.chassis_status:
        reasons.append('底盘状态缺失')
    elif not chassis_online:
        reasons.append(f'底盘未在线: {chassis_state or "missing"}')

    cloud_required = False
    if inputs.voice_session_enabled:
        cloud_required = True
        capabilities['voice_session'] = (
            'ready' if inputs.voice_session_service_ready else 'missing'
        )
        if not inputs.voice_session_service_ready:
            reasons.append('连续语音服务未就绪')
    else:
        capabilities['voice_session'] = 'disabled'

    if inputs.capture_voice_enabled:
        cloud_required = True
        capabilities['capture_voice'] = (
            'ready' if inputs.capture_voice_service_ready else 'missing'
        )
        if not inputs.capture_voice_service_ready:
            reasons.append('单次语音服务未就绪')
    else:
        capabilities['capture_voice'] = 'disabled'

    if inputs.tts_enabled:
        cloud_required = True
        capabilities['tts'] = (
            'speaking' if inputs.tts_speaking
            else 'ready' if inputs.voice_output_present
            else 'missing'
        )
        if not inputs.voice_output_present:
            reasons.append('TTS 节点缺失')
    else:
        capabilities['tts'] = 'disabled'

    capabilities['voice_event'] = (
        f'{max(0.0, inputs.now - inputs.last_voice_event_at):.1f}s ago'
        if inputs.last_voice_event_at > 0.0
        else 'none'
    )

    capabilities['dashscope_key'] = (
        'present' if inputs.dashscope_api_key_present
        else 'missing' if cloud_required
        else 'not_required'
    )
    if cloud_required and not inputs.dashscope_api_key_present:
        reasons.append('ASR/TTS API Key 缺失')

    return HealthResult(not reasons, reasons, capabilities)
