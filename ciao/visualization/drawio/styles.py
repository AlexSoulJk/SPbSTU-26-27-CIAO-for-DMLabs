"""Нативные стили draw.io для диаграмм CIAO."""

from __future__ import annotations

from ciao.domain import AutomatonRole


ROLE_STROKES = {
    AutomatonRole.BASE: "#536478",
    AutomatonRole.CONTROLLER: "#177D9D",
    AutomatonRole.VIEW: "#2C8D75",
}

ROLE_FILLS = {
    AutomatonRole.BASE: "#F1F5F9",
    AutomatonRole.CONTROLLER: "#EAF5FD",
    AutomatonRole.VIEW: "#EBF9F3",
}

QUERY_STROKE = "#B85450"


BLOCK_STYLES = {
    AutomatonRole.BASE: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
        "strokeColor=#536478;strokeWidth=2;verticalAlign=top;"
        "fontStyle=1;spacingTop=10;"
    ),
    AutomatonRole.CONTROLLER: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
        "strokeColor=#177D9D;strokeWidth=2;verticalAlign=top;"
        "fontStyle=1;spacingTop=10;"
    ),
    AutomatonRole.VIEW: (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
        "strokeColor=#2C8D75;strokeWidth=2;verticalAlign=top;"
        "fontStyle=1;spacingTop=10;"
    ),
}

STATE_STYLES = {
    role: (
        "rounded=1;arcSize=15;whiteSpace=wrap;html=1;"
        f"fillColor={ROLE_FILLS[role]};strokeColor={ROLE_STROKES[role]};"
        "strokeWidth=2;fontStyle=1;"
    )
    for role in AutomatonRole
}

FINAL_STATE_STYLES = {
    role: (
        "shape=endState;whiteSpace=wrap;html=1;"
        f"fillColor={ROLE_FILLS[role]};strokeColor={ROLE_STROKES[role]};"
        "strokeWidth=2;fontStyle=1;"
    )
    for role in AutomatonRole
}

ENTRY = (
    "ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#000000;"
    "strokeColor=#000000;strokeWidth=1;"
)
ENTRY_TRANSITION = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
    "jettySize=auto;html=1;endArrow=block;endFill=1;strokeWidth=2;"
    "strokeColor=#000000;"
)
EXIT = (
    "shape=endState;whiteSpace=wrap;html=1;aspect=fixed;"
    "fillColor=#000000;strokeColor=#000000;strokeWidth=2;"
)
STATE_LABEL = (
    "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
    "align=center;verticalAlign=middle;fontStyle=1;"
)
ACTION_LABEL = (
    "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
    "align=center;verticalAlign=middle;"
)

DECISION = (
    "rhombus;perimeter=rhombusPerimeter;whiteSpace=wrap;html=1;"
    "fillColor=#FFF6E2;strokeColor=#D59D35;strokeWidth=2;"
)
CONTEXT_STYLES = {
    AutomatonRole.BASE: (
        "rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
        "fillColor=#F1F5F9;strokeColor=#AAB7C4;spacing=8;"
        "fontFamily=monospace;arcSize=0;"
    ),
    AutomatonRole.CONTROLLER: (
        "rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
        "fillColor=#dae8fc;strokeColor=#6c8ebf;spacing=8;"
        "fontFamily=monospace;arcSize=0;"
    ),
    AutomatonRole.VIEW: (
        "rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
        "fillColor=#d5e8d4;strokeColor=#82b366;spacing=8;"
        "fontFamily=monospace;arcSize=0;"
    ),
}
ENDPOINT_LABEL = (
    "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
    "align=left;verticalAlign=middle;"
)
QUERY_ENDPOINT_LABEL = ENDPOINT_LABEL + f"fontColor={QUERY_STROKE};"
INTERFACE_ANCHOR = (
    "ellipse;whiteSpace=wrap;html=1;fillColor=none;strokeColor=none;"
    "opacity=0;resizable=0;movable=0;rotatable=0;connectable=0;"
)


def endpoint_style(*, provided: bool, side: str, stroke: str) -> str:
    """Возвращает интерфейс, ориентированный к внешней стороне блока."""

    directions = {
        "left": "west",
        "right": "east",
        "top": "north",
        "bottom": "south",
        "external": "south",
    }
    shape = "lollipop" if provided else "requiredInterface"
    rotation = "rotation=-90;" if side in {"bottom", "external"} else ""
    return (
        f"shape={shape};direction={directions[side]};whiteSpace=wrap;html=1;"
        f"fillColor=#FFFFFF;strokeColor={stroke};strokeWidth=2.3;{rotation}"
    )


def required_interface_style(role: AutomatonRole) -> str:
    """Рисует фиксированную ножку с подковой без поворота наконечника."""

    return (
        "edgeStyle=none;rounded=0;orthogonalLoop=1;html=1;"
        "endArrow=halfCircle;endFill=0;endSize=6;strokeWidth=2.3;"
        "sketch=0;fontSize=12;curved=0;noEdgeStyle=1;"
        "exitX=0.5;exitY=0.5;exitDx=0;exitDy=0;exitPerimeter=0;"
        "entryX=0.5;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;"
        "defaultLabelBackgroundColor=page;fillColor=#0050ef;"
        f"strokeColor={ROLE_STROKES[role]};"
    )


def action_interface_style(role: AutomatonRole) -> str:
    """Сохраняет прежнее имя стиля required-интерфейса Action."""

    return required_interface_style(role)


def transition_style(role: AutomatonRole) -> str:
    """Окрашивает переход в цвет роли, сохраняя единый вид стрелки."""

    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
        "jettySize=auto;html=1;whiteSpace=wrap;align=left;"
        "verticalAlign=middle;fontSize=11;resizable=1;"
        "labelBackgroundColor=#FFFFFF;"
        "endArrow=block;endFill=1;strokeWidth=2;"
        f"strokeColor={ROLE_STROKES[role]};"
    )


def external_interface_style(role: AutomatonRole) -> str:
    """Стрелка от внешнего provided-интерфейса к начальному состоянию."""

    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
        "jettySize=auto;html=1;defaultLabelBackgroundColor=page;"
        "entryX=0.327;entryY=0.059;entryDx=0;entryDy=0;entryPerimeter=0;"
        "strokeWidth=2;"
        f"strokeColor={ROLE_STROKES[role]};"
    )


def connection_half_style(
    *,
    required: bool,
    exit_side: str,
    exit_offset: float = 0.5,
    stroke: str = "#000000",
) -> str:
    """Оформляет половину assembly-связи с socket или ball у стыка."""

    exits = {
        "left": f"exitX=0;exitY={exit_offset};exitDx=0;exitDy=0;exitPerimeter=0;",
        "right": f"exitX=1;exitY={exit_offset};exitDx=0;exitDy=0;exitPerimeter=0;",
        "top": f"exitX={exit_offset};exitY=0;exitDx=0;exitDy=0;exitPerimeter=0;",
        "bottom": f"exitX={exit_offset};exitY=1;exitDx=0;exitDy=0;exitPerimeter=0;",
    }
    arrow = "halfCircle" if required else "oval"
    size = "6" if required else "10"
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
        "jettySize=auto;html=1;"
        f"endArrow={arrow};endFill=0;endSize={size};strokeWidth=1;"
        f"strokeColor={stroke};"
        "sketch=0;defaultLabelBackgroundColor=page;"
        f"{exits[exit_side]}"
    )


CONNECTION_JUNCTION = (
    "ellipse;whiteSpace=wrap;html=1;align=center;aspect=fixed;"
    "fillColor=none;strokeColor=none;resizable=0;perimeter=centerPerimeter;"
    "rotatable=0;allowArrows=0;points=[];outlineConnect=1;"
)
CONNECTION_LABEL = (
    "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
    "align=center;verticalAlign=middle;rounded=0;"
)


def connection_label_style(stroke: str) -> str:
    """Окрашивает только семантическую подпись, не меняя assembly-нотацию."""

    return CONNECTION_LABEL + f"fontColor={stroke};"
