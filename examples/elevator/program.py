from dataclasses import dataclass

from ciao import Connection, Program, AutomatonObject

from .automatos import (
    ElevatorController,
    ElevatorControllerContext,
    Device,
    DeviceContext,
)

def build_sample_row() -> Program:
    # Constructor signatures may differ in the local CIAO version.
    
    controller = AutomatonObject(
            "controller",
            ElevatorController,
            ElevatorControllerContext(),
        )
    
    
    door = AutomatonObject(
                "door",
                Device,
                DeviceContext(),
            )
    light = AutomatonObject(
                "light",
                Device,
                DeviceContext(),
            )
    cabin = AutomatonObject(
                "cabin",
                Device,
                DeviceContext(),
            )

    connections = [
        Connection(required=(controller, ElevatorController.open_door),
                   provided=(door, Device.on)),
        Connection(required=(controller, ElevatorController.close_door),
                   provided=(door, Device.off)),
        Connection(required=(controller, ElevatorController.switch_on),
                   provided=(light, Device.on)),
        Connection(required=(controller, ElevatorController.switch_off),
                   provided=(light, Device.off)),
        Connection(required=(controller, ElevatorController.occupy),
                   provided=(cabin, Device.on)),
        Connection(required=(controller, ElevatorController.free),
                   provided=(cabin, Device.off)),
        Connection(required=(controller, ElevatorController.occupied),
                   provided=(cabin, Device.is_on)),
    ]

    return Program(
        objects=[controller, door, light, cabin],
        connections=connections,
    )