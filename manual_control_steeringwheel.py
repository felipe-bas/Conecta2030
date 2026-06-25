#!/usr/bin/env python

# Copyright (c) 2019 Intel Labs
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

# Allows controlling a vehicle with a keyboard. For a simpler and more
# documented example, please take a look at tutorial.py.

"""
Welcome to CARLA manual control with steering wheel Logitech G29.

To drive start by preshing the brake pedal.
Change your wheel_config.ini according to your steering wheel.

To find out the values of your steering wheel use jstest-gtk in Ubuntu.

"""

from __future__ import print_function


# ==============================================================================
# -- find carla module ---------------------------------------------------------
# ==============================================================================


import glob
import os
import sys

try:
    sys.path.append(glob.glob('../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass


# ==============================================================================
# -- imports -------------------------------------------------------------------
# ==============================================================================


import carla  # type: ignore

try:
    import pandas as pd
    from sklearn.neighbors import NearestNeighbors
except ImportError:
    pd = None
    NearestNeighbors = None

from carla import ColorConverter as cc  # type: ignore

try:
    from logidrivepy import LogitechController
    LOGITECH_AVAILABLE = True
except ImportError:
    LOGITECH_AVAILABLE = False
    # Dummy class for when logidrivepy is not installed/supported (e.g. Linux)
    class LogitechController(object):
        def steering_initialize(self): return False
        def is_connected(self, index): return False
        def logi_update(self): pass
        def LogiPlaySpringForce(self, *args, **kwargs): pass
        def steering_shutdown(self): pass

import pure_pursuit
import numpy as np
import collections
import threading
import argparse
import datetime
import logging
import weakref
import socket
import random
import time
import json
import math
import re

if sys.version_info >= (3, 0):

    from configparser import ConfigParser

else:

    from ConfigParser import RawConfigParser as ConfigParser

try:
    import pygame
    from pygame.locals import KMOD_CTRL
    from pygame.locals import KMOD_SHIFT
    from pygame.locals import K_0
    from pygame.locals import K_9
    from pygame.locals import K_BACKQUOTE
    from pygame.locals import K_BACKSPACE
    from pygame.locals import K_COMMA
    from pygame.locals import K_DOWN
    from pygame.locals import K_ESCAPE
    from pygame.locals import K_F1
    from pygame.locals import K_LEFT
    from pygame.locals import K_PERIOD
    from pygame.locals import K_RIGHT
    from pygame.locals import K_SLASH
    from pygame.locals import K_SPACE
    from pygame.locals import K_TAB
    from pygame.locals import K_UP
    from pygame.locals import K_a
    from pygame.locals import K_c
    from pygame.locals import K_d
    from pygame.locals import K_h
    from pygame.locals import K_m
    from pygame.locals import K_p
    from pygame.locals import K_q
    from pygame.locals import K_r
    from pygame.locals import K_s
    from pygame.locals import K_w
except ImportError:
    raise RuntimeError(
        'cannot import pygame, make sure pygame package is installed')

try:
    import numpy as np
except ImportError:
    raise RuntimeError(
        'cannot import numpy, make sure numpy package is installed')

# vid = 0x046D  # Vendor ID
# pid = 0xC24F  # Product ID
# device = hid.device()
# device.open(vid, pid)

# ==============================================================================
# -- Global functions ----------------------------------------------------------
# ==============================================================================


def find_weather_presets():
    rgx = re.compile('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)')
    def name(x): return ' '.join(m.group(0) for m in rgx.finditer(x))
    presets = [x for x in dir(carla.WeatherParameters)
               if re.match('[A-Z].+', x)]
    return [(getattr(carla.WeatherParameters, x), name(x)) for x in presets]


def load_v2x_ddns_config():
    """Lê o arquivo v2x_ddns.conf ao lado do script para descoberta automática do RSU.
    Retorna dict com ddns_url, rsu_name, udp_port."""
    config = {
        'ddns_url': 'http://localhost:5000',
        'rsu_name': 'rsu-v2x',
        'udp_port': 9090,
    }
    conf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v2x_ddns.conf')
    try:
        with open(conf_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip()
                    if key == 'ddns_url':
                        config['ddns_url'] = val
                    elif key == 'rsu_name':
                        config['rsu_name'] = val
                    elif key == 'udp_port':
                        config['udp_port'] = int(val)
        print(f"[DDNS] Config carregado: {conf_path}")
        print(f"[DDNS]   servidor: {config['ddns_url']}")
        print(f"[DDNS]   rsu_name: {config['rsu_name']}")
        print(f"[DDNS]   udp_port: {config['udp_port']}")
    except FileNotFoundError:
        print(f"[DDNS] Arquivo {conf_path} não encontrado, usando padrões (localhost:5000)")
    except Exception as e:
        print(f"[DDNS] Erro ao ler config: {e}")
    return config


def resolve_from_ddns(name, registry_url="http://localhost:5000"):
    """Consulta o servidor DDNS para obter o IP (IPv4 ou IPv6) de um nó."""
    try:
        import requests
        resp = requests.get(f"{registry_url}/resolve?name={name}", timeout=5)
        if resp.status_code == 200:
            ip = resp.text.strip()
            if ip:
                print(f"[DDNS] {name} → {ip} (via {registry_url})")
                return ip
            else:
                print(f"[DDNS] {name} retornou IP vazio")
        else:
            print(f"[DDNS] {name} não encontrado (HTTP {resp.status_code})")
    except Exception as e:
        print(f"[DDNS] Falha ao consultar {registry_url}: {e}")
    return None


def auto_discover_rsu():
    """Descoberta automática do RSU via DDNS.
    Lê v2x_ddns.conf, consulta o servidor DDNS, retorna (ip, port) ou (None, port)."""
    config = load_v2x_ddns_config()
    rsu_ip = resolve_from_ddns(config['rsu_name'], registry_url=config['ddns_url'])
    return rsu_ip, config['udp_port']

def get_actor_display_name(actor, truncate=250):
    name = ' '.join(actor.type_id.replace('_', '.').title().split('.')[1:])
    return (name[:truncate - 1] + u'\u2026') if len(name) > truncate else name

# ==============================================================================
# -- World ---------------------------------------------------------------------
# ==============================================================================


class World(object):
    def __init__(self, carla_world, hud, actor_filter, logi_controller, steeringwheel):
        print("[DEBUG] World init started")
        self.world = carla_world
        self.hud = hud
        self.player = None
        self.walker = None
        self.collision_sensor = None
        self.lane_invasion_sensor = None
        self.gnss_sensor = None
        self.camera_manager = None
        self.camera_infra_sensor = None
        self.lidar_sensor = None
        self._weather_presets = find_weather_presets()
        self._weather_index = 4 # 1 2 ou 4
        self._actor_filter = actor_filter
        self.logi_controller = logi_controller
        self.steeringwheel = steeringwheel
        print("[DEBUG] Calling restart()")
        self.restart()
        print("[DEBUG] Calling on_tick()")
        self.world.on_tick(hud.on_world_tick)
        print("[DEBUG] World init finished")

    def restart(self):
        print("[DEBUG] restart(): getting camera index")
        # Keep same camera config if the camera manager exists.
        cam_index = self.camera_manager.index if self.camera_manager is not None else 0
        cam_pos_index = self.camera_manager.transform_index if self.camera_manager is not None else 0
        
        print("[DEBUG] restart(): fetching blueprints")
        # Get a random blueprint.
        bp_list = self.world.get_blueprint_library().filter('vehicle.jeep.wrangler_rubicon')
        if len(bp_list) == 0:
            print("[WARN] Blueprint 'vehicle.jeep.wrangler_rubicon' not found, trying 'vehicle.*'")
            bp_list = self.world.get_blueprint_library().filter('vehicle.*')
        if len(bp_list) == 0:
            raise RuntimeError("No vehicle blueprints found in the CARLA server. Is the server running?")
        blueprint = random.choice(bp_list)
        
        blueprint.set_attribute('role_name', 'hero')

        print("[DEBUG] restart(): fetching walker blueprint")
        walker_bp = self.world.get_blueprint_library().filter('walker.*')[0]
            
        # Configurações adicionais do blueprint
        if blueprint.has_attribute('terramechanics'):
            blueprint.set_attribute('terramechanics', 'true')

        if blueprint.has_attribute('color'):
            color = random.choice(blueprint.get_attribute('color').recommended_values)
            blueprint.set_attribute('color', color)

        if blueprint.has_attribute('driver_id'):
            driver_id = random.choice(blueprint.get_attribute('driver_id').recommended_values)
            blueprint.set_attribute('driver_id', driver_id)

        if blueprint.has_attribute('is_invincible'):
            blueprint.set_attribute('is_invincible', 'true')

        # Velocidade máxima do veículo
        if blueprint.has_attribute('speed'):
            speed_values = blueprint.get_attribute('speed').recommended_values
            if len(speed_values) >= 3:
                self.player_max_speed = float(speed_values[1])
                self.player_max_speed_fast = float(speed_values[2])

        # Spawn the player.
        if self.player is not None:
            print("[DEBUG] restart(): cleaning up old player")
            spawn_point = self.player.get_transform()
            spawn_point.location.z += 2.0
            spawn_point.rotation.roll = 0.0
            spawn_point.rotation.pitch = 0.0
            self.destroy()
            self.player = self.world.try_spawn_actor(blueprint, spawn_point)
            self.modify_vehicle_physics(self.player)
        print("[DEBUG] restart(): getting spawn points")
        spawn_points = self.world.get_map().get_spawn_points()
        spawn_idx = 10
        print("[DEBUG] restart(): entering spawn loop")
        while self.player is None:
            if not spawn_points:
                print("[ERROR] No spawn points found on the map!")
                break
            
            spawn_point = spawn_points[spawn_idx] if spawn_idx < len(spawn_points) else random.choice(spawn_points)
            self.player = self.world.try_spawn_actor(blueprint, spawn_point)
            
            if self.player is None:
                print(f"[WARN] Falha ao spawnar veículo no ponto {spawn_idx}. Tentando outro ponto aleatório...")
                spawn_idx = random.randint(0, len(spawn_points) - 1)
                time.sleep(0.5)
            else:
                self.modify_vehicle_physics(self.player)
        print("[DEBUG] restart(): player spawned, setting up sensors")
        # Set up the sensors.
        self.collision_sensor = CollisionSensor(self.player, self.hud, self.logi_controller, self.steeringwheel)
        self.lane_invasion_sensor = LaneInvasionSensor(self.player, self.hud)
        self.gnss_sensor = GnssSensor(self.player)
        self.camera_manager = CameraManager(self.player, self.hud, self.steeringwheel)
        self.camera_manager.transform_index = cam_pos_index
        self.camera_manager.set_sensor(cam_index, notify=False)
        self.camera_infra_sensor = CameraInfra(self.player, self.hud)
        self.lidar_sensor = LidarSensor(self.player)
        self.world.debug.draw_point(self.lidar_sensor.sensor.get_transform().location, size=0.2, color=carla.Color(255,0,0), life_time=10.0)
        print("[DEBUG] restart(): getting display name")
        actor_type = get_actor_display_name(self.player)
        self.hud.notification(actor_type)

    def next_weather(self, reverse=False):
        self._weather_index += -1 if reverse else 1
        self._weather_index %= len(self._weather_presets)
        preset = self._weather_presets[self._weather_index]
        self.hud.notification('Weather: %s' % preset[1])
        self.player.get_world().set_weather(preset[0])
        
    def modify_vehicle_physics(self, actor):
        #If actor is not a vehicle, we cannot use the physics control
        try:
            physics_control = actor.get_physics_control()
            
            
            #Torque Motor
            physics_control.torque_curve = [
                carla.Vector2D(0,     150),   # Marcha lenta / spool inicial
                carla.Vector2D(1000,  230),
                carla.Vector2D(1500,  265),   # turbo enchendo
                carla.Vector2D(1750,  270),   # torque máximo
                carla.Vector2D(3000,  265),
                carla.Vector2D(4000,  250),
                carla.Vector2D(5000,  210),
                carla.Vector2D(5750,  185),   # conversão aproximada da potência em torque
                carla.Vector2D(6000,  0), 
                ]
            
            physics_control.max_rpm = 6000
            physics_control.moi = 0.4
            physics_control.damping_rate_full_throttle = 0.15
            
            #Transmissão 
            physics_control.use_gear_autobox = True
            physics_control.gear_switch_time = 0.45
            physics_control.clutch_strength = 8.0

            new_gears = [
                carla.GearPhysicsControl(ratio=4.72, down_ratio=0.5, up_ratio=0.65),   # 1ª
                carla.GearPhysicsControl(ratio=2.91, down_ratio=0.5, up_ratio=0.65),   # 2ª
                carla.GearPhysicsControl(ratio=1.86, down_ratio=0.5, up_ratio=0.65),   # 3ª
                carla.GearPhysicsControl(ratio=1.42, down_ratio=0.5, up_ratio=0.65),   # 4ª
                carla.GearPhysicsControl(ratio=1.22, down_ratio=0.5, up_ratio=0.65),   # 5ª
                carla.GearPhysicsControl(ratio=1.00, down_ratio=0.5, up_ratio=0.65),   # 6ª
                carla.GearPhysicsControl(ratio=0.79, down_ratio=0.5, up_ratio=0.65),   # 7ª
                carla.GearPhysicsControl(ratio=0.64, down_ratio=0.5, up_ratio=0.65),   # 8ª
            ]

            physics_control.forward_gears = new_gears

            physics_control.final_ratio = 3.730
        
            #Test Zone
            #physics_control.use_sweep_wheel_collision = 0
            
            #Direção 
            physics_control.steering_curve = [
                carla.Vector2D(0, 1.0),
                carla.Vector2D(30, 0.8),
                carla.Vector2D(100, 0.5)
            ]
            
            
            #Rodas e Suspensão
            front_left_wheel  = carla.WheelPhysicsControl(tire_friction=1.3, damping_rate=0.5, max_steer_angle=35.0, radius=38, long_stiff_value=80000)
            front_right_wheel = carla.WheelPhysicsControl(tire_friction=1.3, damping_rate=0.5, max_steer_angle=35.0, radius=38, long_stiff_value=80000)
            rear_left_wheel   = carla.WheelPhysicsControl(tire_friction=1.3, damping_rate=0.5, max_steer_angle=0.0,  radius=38, long_stiff_value=80000)
            rear_right_wheel  = carla.WheelPhysicsControl(tire_friction=1.3, damping_rate=0.5, max_steer_angle=0.0,  radius=38, long_stiff_value=80000)

            wheels = [front_left_wheel, front_right_wheel, rear_left_wheel, rear_right_wheel]
            
            #Peso e arrasto
            physics_control.mass = 1630
            physics_control.drag_coefficient = 0.33
            
            physics_control.use_sweep_wheel_collision = True
            physics_control.center_of_mass = carla.Vector3D(x=0.0, y=0.0, z=-0.5)
            physics_control.wheels = wheels
            actor.apply_physics_control(physics_control)
            #print(physics_control)
            #print(physics_control.center_of_mass)
            
        except Exception:
            pass
        
    def modify_vehicle_physics2(self, actor):
        #If actor is not a vehicle, we cannot use the physics control
    
        # Create Wheels Physics Control
        front_left_wheel  = carla.WheelPhysicsControl(tire_friction=2.0, damping_rate=1.5, max_steer_angle=10.0, long_stiff_value=10)
        front_right_wheel = carla.WheelPhysicsControl(tire_friction=2.0, damping_rate=1.5, max_steer_angle=10.0, long_stiff_value=10)
        rear_left_wheel   = carla.WheelPhysicsControl(tire_friction=3.0, damping_rate=1.5, max_steer_angle=0.0,  long_stiff_value=10)
        rear_right_wheel  = carla.WheelPhysicsControl(tire_friction=3.0, damping_rate=1.5, max_steer_angle=0.0,  long_stiff_value=10)

        wheels = [front_left_wheel, front_right_wheel, rear_left_wheel, rear_right_wheel]

        # Change Vehicle Physics Control parameters of the vehicle
        physics_control = actor.get_physics_control()
        
        #physics_control.center_of_mass = carla.Vector3D(x=0.0, y=0.1, z=-0.2)
        print (physics_control.center_of_mass)
        physics_control.torque_curve = [carla.Vector2D(x=0, y=400), carla.Vector2D(x=1300, y=600)]
        physics_control.max_rpm = 10000
        physics_control.moi = 1.0
        physics_control.damping_rate_full_throttle = 0.0
        physics_control.use_gear_autobox = True
        physics_control.gear_switch_time = 0.5
        physics_control.clutch_strength = 10
        physics_control.mass = 10000
        physics_control.drag_coefficient = 0.25
        physics_control.steering_curve = [carla.Vector2D(x=0, y=1), carla.Vector2D(x=100, y=1), carla.Vector2D(x=300, y=1)]

        
        physics_control.use_sweep_wheel_collision = True
        actor.apply_physics_control(physics_control)

    def tick(self, clock):
        self.hud.tick(self, clock)
        # veiculo = self.player
        # rpm = audiomanager.estimar_rpm(veiculo) #----------------------#
        # print(f"RPM estimado: {rpm:.2f}")

    def render(self, display):
        self.camera_manager.render(display)
        self.hud.render(display)

    def destroy(self):
        sensors = [
            self.camera_manager.sensor,
            self.collision_sensor.sensor,
            self.lane_invasion_sensor.sensor,
            self.gnss_sensor.sensor,
            self.lidar_sensor.sensor,
            self.camera_infra_sensor.sensor]
        for sensor in sensors:
            if sensor is not None:
                sensor.stop()
                sensor.destroy()
        if self.player is not None:
            self.player.destroy()
        if self.walker is not None:
            self.walker.destroy()


# ==============================================================================
# -- DualControl -----------------------------------------------------------
# ==============================================================================


class DualControl(object):
    def __init__(self, world, start_in_autopilot, steeringwheel):
        self._autopilot_enabled = start_in_autopilot
        self.steeringwheel = steeringwheel
        if isinstance(world.player, carla.Vehicle):
            self._control = carla.VehicleControl()
            self._lights = carla.VehicleLightState.NONE
            world.player.set_light_state(self._lights)
            world.player.set_autopilot(self._autopilot_enabled)
            self._control = carla.VehicleControl()
            self._ackermann_control = carla.VehicleAckermannControl()
        elif isinstance(world.player, carla.Walker):
            self._control = carla.WalkerControl()
            self._autopilot_enabled = False
            self._rotation = world.player.get_transform().rotation
        else:
            raise NotImplementedError("Actor type not supported")
        self._steer_cache = 0.0
        world.hud.notification("Press 'H' or '?' for help.", seconds=4.0)

        if self.steeringwheel == True:
            # initialize steering wheel
            pygame.joystick.init()

            joystick_count = pygame.joystick.get_count()
            if joystick_count > 1:
                raise ValueError("Please Connect Just One Joystick")

            self._joystick = pygame.joystick.Joystick(0)
            self._joystick.init()

            self._parser = ConfigParser()
            self._parser.read('./wheel_config.ini')
            self._steer_idx = int(self._parser.get(
                'G29 Racing Wheel', 'steering_wheel'))
            self._throttle_idx = int(self._parser.get(
                'G29 Racing Wheel', 'throttle'))
            self._brake_idx = int(self._parser.get('G29 Racing Wheel', 'brake'))
            self._reverse_idx = int(self._parser.get(
                'G29 Racing Wheel', 'reverse'))
            self._handbrake_idx = int(self._parser.get(
                'G29 Racing Wheel', 'handbrake'))

        # Inicializa som
        pygame.mixer.init()
        self.turn_signal_sound = pygame.mixer.Sound(
            "./audio/CarSetaCurt2.wav")
        self.turn_signal_sound.set_volume(10)
        self.horn_sound = pygame.mixer.Sound(
            "./audio/CarHorn.wav")

        # Estado das setas
        self.left_signal_active = False
        self.right_signal_active = False

    def parse_events(self, world, clock):
        if isinstance(self._control, carla.VehicleControl):
            current_lights = self._lights  # Aciona as Luzes
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True

            elif event.type == pygame.JOYBUTTONDOWN:
                if event.button == 0:
                    world.restart()
                elif event.button == 1:
                    world.hud.toggle_info()
                elif event.button == 2:
                    world.camera_manager.toggle_camera()
                elif event.button == 3:
                    world.next_weather()
                elif event.button == 6:
                    self.horn_sound.play()  # horn
                elif event.button == 10: #volante 12
                    self._control.gear = 1
                elif event.button == 13:
                    self._control.gear = 2
                elif event.button == 14:
                    self._control.gear = 3
                elif event.button == 15:
                    self._control.gear = 4
                elif event.button == 16:
                    self._control.gear = 5
                elif event.button == 17:
                    self._control.gear = 6
                elif event.button == self._reverse_idx:
                    self._control.gear = -1
                elif event.button == 21:
                    world.camera_manager.move_x()
                elif event.button == 23:
                    world.camera_manager.next_sensor()
                elif event.button == 11 and pygame.key.get_mods() & KMOD_CTRL:  # Representa "L"
                    current_lights ^= carla.VehicleLightState.Special1
                elif event.button == 11 and pygame.key.get_mods() & KMOD_SHIFT:  # Representa "L"
                    current_lights ^= carla.VehicleLightState.HighBeam
                elif event.button == 11:
                    # print(event.button)

                    # Use 'L' key to switch between lights:
                    # closed -> position -> low beam -> fog
                    if not self._lights & carla.VehicleLightState.Position:
                        world.hud.notification("Position lights")
                        current_lights |= carla.VehicleLightState.Position
                    else:
                        world.hud.notification("Low beam lights")
                        current_lights |= carla.VehicleLightState.LowBeam
                    if self._lights & carla.VehicleLightState.LowBeam:
                        world.hud.notification("Fog lights")
                        current_lights |= carla.VehicleLightState.Fog
                    if self._lights & carla.VehicleLightState.Fog:
                        world.hud.notification("Lights off")
                        current_lights ^= carla.VehicleLightState.Position
                        current_lights ^= carla.VehicleLightState.LowBeam
                        current_lights ^= carla.VehicleLightState.Fog
                elif event.button == 10: #volante 10
                    current_lights ^= carla.VehicleLightState.Interior

                elif event.button == 5:   # Botão da seta esquerda
                    current_lights ^= carla.VehicleLightState.LeftBlinker
                    self.left_signal_active = not self.left_signal_active

                    if self.left_signal_active:
                        print("Seta esquerda ativada")
                        self.turn_signal_sound.play(loops=-1)
                    else:
                        print("Seta esquerda desativada")
                        # Para o som só se a direita não estiver ativa
                        if not self.right_signal_active:
                            self.turn_signal_sound.stop()

                elif event.button == 4:  # Botão da seta direita
                    current_lights ^= carla.VehicleLightState.RightBlinker
                    self.right_signal_active = not self.right_signal_active

                    if self.right_signal_active:
                        print("Seta direita ativada")
                        self.turn_signal_sound.play(loops=-1)
                    else:
                        print("Seta direita desativada")
                        # Para o som só se a esquerda não estiver ativa
                        if not self.left_signal_active:
                            self.turn_signal_sound.stop()

            elif event.type == pygame.JOYBUTTONUP:
                if event.button in [12, 13, 14, 15, 16, 17, 18]:
                    self._control.gear = 0

            elif event.type == pygame.KEYUP:
                if self._is_quit_shortcut(event.key):
                    return True
                elif event.key == K_BACKSPACE:
                    world.restart()
                elif event.key == K_F1:
                    world.hud.toggle_info()
                elif event.key == K_h or (event.key == K_SLASH and pygame.key.get_mods() & KMOD_SHIFT):
                    world.hud.help.toggle()
                elif event.key == K_TAB:
                    world.camera_manager.toggle_camera()
                elif event.key == K_c and pygame.key.get_mods() & KMOD_SHIFT:
                    world.next_weather(reverse=True)
                elif event.key == K_c:
                    world.next_weather()
                elif event.key == K_BACKQUOTE:
                    world.camera_manager.next_sensor()
                elif event.key > K_0 and event.key <= K_9:
                    world.camera_manager.set_sensor(event.key - 1 - K_0)
                elif event.key == K_r:
                    world.camera_manager.toggle_recording()
                if isinstance(self._control, carla.VehicleControl):
                    if event.key == K_q:
                        self._control.gear = 1 if self._control.reverse else -1
                    elif event.key == K_m:
                        self._control.manual_gear_shift = not self._control.manual_gear_shift
                        self._control.gear = world.player.get_control().gear
                        world.hud.notification('%s Transmission' %
                                               ('Manual' if self._control.manual_gear_shift else 'Automatic'))
                    elif self._control.manual_gear_shift and event.key == K_COMMA:
                        self._control.gear = max(-1, self._control.gear - 1)
                    elif self._control.manual_gear_shift and event.key == K_PERIOD:
                        self._control.gear = self._control.gear + \
                            1 if self._control.gear < 6 else self._control.gear
                    elif event.key == K_p:
                        self._autopilot_enabled = not self._autopilot_enabled
                        world.player.set_autopilot(self._autopilot_enabled)
                        world.hud.notification('Autopilot %s' % (
                            'On' if self._autopilot_enabled else 'Off'))

        if not self._autopilot_enabled:
            if isinstance(self._control, carla.VehicleControl):
                self._parse_vehicle_keys(
                    pygame.key.get_pressed(), clock.get_time())
                if self.steeringwheel == True: self._parse_vehicle_wheel()
                self._control.reverse = self._control.gear < 0

            # Linhas adicionais para acionar as luzes
            if self._control.brake:
                current_lights |= carla.VehicleLightState.Brake
            else:  # Remove the Brake flag
                current_lights &= ~carla.VehicleLightState.Brake
            if self._control.reverse:
                current_lights |= carla.VehicleLightState.Reverse
            else:  # Remove the Reverse flag
                current_lights &= ~carla.VehicleLightState.Reverse
            if current_lights != self._lights:  # Change the light state only if necessary
                self._lights = current_lights
                world.player.set_light_state(
                    carla.VehicleLightState(self._lights))

            if current_lights != self._lights:  # Change the light state only if necessary
                self._lights = current_lights
                world.player.set_light_state(
                    carla.VehicleLightState(self._lights))

            elif isinstance(self._control, carla.WalkerControl):
                self._parse_walker_keys(
                    pygame.key.get_pressed(), clock.get_time())
            world.player.apply_control(self._control)

    def _parse_vehicle_keys(self, keys, milliseconds):
        self._control.throttle = 1.0 if keys[K_UP] or keys[K_w] else 0.0
        steer_increment = 5e-4 * milliseconds
        if keys[K_LEFT] or keys[K_a]:
            self._steer_cache -= steer_increment
        elif keys[K_RIGHT] or keys[K_d]:
            self._steer_cache += steer_increment
        else:
            self._steer_cache = 0.0
        self._steer_cache = min(0.7, max(-0.7, self._steer_cache))
        self._control.steer = round(self._steer_cache, 1)
        self._control.brake = 1.0 if keys[K_DOWN] or keys[K_s] else 0.0
        self._control.hand_brake = keys[K_SPACE]

    def _parse_vehicle_wheel(self):
        numAxes = self._joystick.get_numaxes()
        jsInputs = [float(self._joystick.get_axis(i)) for i in range(numAxes)]
        # print (jsInputs)
        jsButtons = [float(self._joystick.get_button(i)) for i in
                     range(self._joystick.get_numbuttons())]

        # Custom function to map range of inputs [1, -1] to outputs [0, 1] i.e 1 from inputs means nothing is pressed
        # For the steering, it seems fine as it is
        K1 = 1.0  # 0.55
        steerCmd = K1 * math.tan(1.1 * jsInputs[self._steer_idx])

        K2 = 1.6  # 1.6
        throttleCmd = K2 + (2.05 * math.log10(
            -0.7 * jsInputs[self._throttle_idx] + 1.4) - 1.2) / 0.92
        if throttleCmd <= 0:
            throttleCmd = 0

        elif throttleCmd > 1:
            throttleCmd = 1

        brakeCmd = 1.6 + (2.05 * math.log10(
            -0.7 * jsInputs[self._brake_idx] + 1.4) - 1.2) / 0.92
        if brakeCmd <= 0:
            brakeCmd = 0
        elif brakeCmd > 1:
            brakeCmd = 1

        self._control.steer = steerCmd
        self._control.brake = brakeCmd
        self._control.throttle = throttleCmd

        # toggle = jsButtons[self._reverse_idx]

        self._control.hand_brake = bool(jsButtons[self._handbrake_idx])

    def _parse_walker_keys(self, keys, milliseconds):
        self._control.speed = 0.0
        if keys[K_DOWN] or keys[K_s]:
            self._control.speed = 0.0
        if keys[K_LEFT] or keys[K_a]:
            self._control.speed = .01
            self._rotation.yaw -= 0.08 * milliseconds
        if keys[K_RIGHT] or keys[K_d]:
            self._control.speed = .01
            self._rotation.yaw += 0.08 * milliseconds
        if keys[K_UP] or keys[K_w]:
            self._control.speed = 5.556 if pygame.key.get_mods() & KMOD_SHIFT else 2.778
        self._control.jump = keys[K_SPACE]
        self._rotation.yaw = round(self._rotation.yaw, 1)
        self._control.direction = self._rotation.get_forward_vector()

    @staticmethod
    def _is_quit_shortcut(key):
        return (key == K_ESCAPE) or (key == K_q and pygame.key.get_mods() & KMOD_CTRL)

# ==============================================================================
# -- Audio() --------------------------------------------------------------------
# ==============================================================================


class AudioManager:

    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        pygame.mixer.Sound(
            "./audio/CarStart.wav").play()
        self.idle_sound = pygame.mixer.Sound(
            "./audio/IdleCarSound.wav")
        self.accel_sound = pygame.mixer.Sound(
            "./audio/testeAceleraçãoCompleto.wav")
        self.decel_sound = pygame.mixer.Sound(
            "./audio/testeDesaceleraçãoCompleto.wav")
        self.idle_playing = False
        self.accel_playing = False
        self.decel_playing = False
        self.last_speed = 0.0

    def som(self, throttle, speed):
        current_speed = speed
        speed_diff = current_speed - self.last_speed

        # Prioridade: se throttle == 0 e velocidade quase zero, toca idle e sai
        if throttle == 0 and current_speed < 0.1:
            if not self.idle_playing:
                self.idle_sound.play(-1)
                self.idle_playing = True
            if self.accel_playing:
                self.accel_sound.stop()
                self.accel_playing = False
            if self.decel_playing:
                self.decel_sound.stop()
                self.decel_playing = False
            self.last_speed = current_speed
            return  # para evitar tocar decel também

        # Se throttle == 0 e velocidade está diminuindo, toca deceleração
        if throttle == 0 and speed_diff < 0:
            if not self.decel_playing:
                self.decel_sound.play(-1)
                self.decel_playing = True
            if self.idle_playing:
                self.idle_sound.stop()
                self.idle_playing = False
            if self.accel_playing:
                self.accel_sound.stop()
                self.accel_playing = False

        # Se throttle > 0.1 e velocidade > 0, toca aceleração
        elif throttle > 0.1 and current_speed > 0:
            if not self.accel_playing:
                self.accel_sound.play(-1)
                self.accel_playing = True
            if self.idle_playing:
                self.idle_sound.stop()
                self.idle_playing = False
            if self.decel_playing:
                self.decel_sound.stop()
                self.decel_playing = False

        self.last_speed = current_speed

    def estimar_rpm(self, veiculo):
        controle = veiculo.get_control()
        fisica = veiculo.get_physics_control()
        rpm_estimado = fisica.max_rpm * controle.throttle
        if controle.gear > 0:
            marcha = fisica.forward_gears[controle.gear - 1]
            rpm_estimado *= marcha.ratio
        return rpm_estimado


# ==============================================================================
# -- HUD -----------------------------------------------------------------------
# ==============================================================================

audiomanager = AudioManager()


class HUD(object):

    def __init__(self, width, height):
        self.dim = (width, height)
        font = pygame.font.Font(pygame.font.get_default_font(), 20)
        font_name = 'courier' if os.name == 'nt' else 'mono'
        fonts = [x for x in pygame.font.get_fonts() if font_name in x]
        default_font = 'ubuntumono'
        mono = default_font if default_font in fonts else fonts[0]
        mono = pygame.font.match_font(mono)
        self._font_mono = pygame.font.Font(mono, 12 if os.name == 'nt' else 14)
        self._notifications = FadingText(font, (width, 40), (0, height - 40))
        self.help = HelpText(pygame.font.Font(mono, 24), width, height)
        self.server_fps = 0
        self.frame = 0
        self.simulation_time = 0
        self._show_info = True
        self._info_text = []
        self._server_clock = pygame.time.Clock()

    def on_world_tick(self, timestamp):
        self._server_clock.tick(0) #fps server
        self.server_fps = self._server_clock.get_fps()
        self.frame = timestamp.frame
        self.simulation_time = timestamp.elapsed_seconds

    def save_lat_lon(self, lat, lon, x, y, yaw, filename='coordinates.csv'):
        with open(filename, 'a') as f:
            f.write(f"{lat},{lon},{x},{y},{yaw}\n")
        
    def tick(self, world, clock):
        self._notifications.tick(world, clock)
        if not self._show_info:
            return
        t = world.player.get_transform()
        v = world.player.get_velocity()
        c = world.player.get_control()

        heading = 'N' if abs(t.rotation.yaw) < 89.5 else ''
        heading += 'S' if abs(t.rotation.yaw) > 90.5 else ''
        heading += 'E' if 179.5 > t.rotation.yaw > 0.5 else ''
        heading += 'W' if -0.5 > t.rotation.yaw > -179.5 else ''
        colhist = world.collision_sensor.get_collision_history()
        collision = [colhist[x + self.frame - 200] for x in range(0, 200)]
        max_col = max(1.0, max(collision))
        collision = [x / max_col for x in collision]
        vehicles = world.world.get_actors().filter('vehicle.*')

        self._info_text = [
            'Server:  % 16.0f FPS' % self.server_fps,
            'Client:  % 16.0f FPS' % clock.get_fps(),
            '',
            'Vehicle: % 20s' % get_actor_display_name(
                world.player, truncate=20),
            'Map:     % 20s' % world.world.get_map().name.split('/')[-1],
            'Simulation time: % 12s' % datetime.timedelta(
                seconds=int(self.simulation_time)),
            '',
            'Speed:   % 15.0f km/h' % (3.6 *
                                       math.sqrt(v.x**2 + v.y**2 + v.z**2)),
            u'Heading:% 16.0f\N{DEGREE SIGN} % 2s' % (t.rotation.yaw, heading),
            'Location:% 20s' % ('(% 5.1f, % 5.1f)' %
                                (t.location.x, t.location.y)),
            'GNSS:% 24s' % ('(% 2.6f, % 3.6f)' %
                            (world.gnss_sensor.lat, world.gnss_sensor.lon)),
            'Height:  % 18.0f m' % t.location.z,
            '']
        if isinstance(c, carla.VehicleControl):
            self._info_text += [
                ('Throttle:', c.throttle, 0.0, 1.0),
                ('Steer:', c.steer, -1.0, 1.0),
                ('Brake:', c.brake, 0.0, 1.0),
                ('Reverse:', c.reverse),
                ('Hand brake:', c.hand_brake),
                ('Manual:', c.manual_gear_shift),
                'Gear:        %s' % {-1: 'R', 0: 'N'}.get(c.gear, c.gear)]
        elif isinstance(c, carla.WalkerControl):
            self._info_text += [
                ('Speed:', c.speed, 0.0, 5.556),
                ('Jump:', c.jump)]
        self._info_text += [
            '',
            'Collision:',
            collision,
            '',
            'Number of vehicles: % 8d' % len(vehicles)]
        if len(vehicles) > 1:
            self._info_text += ['Nearby vehicles:']
            def distance(l): return math.sqrt((l.x - t.location.x) **
                                              2 + (l.y - t.location.y)**2 + (l.z - t.location.z)**2)
            vehicles = [(distance(x.get_location()), x)
                        for x in vehicles if x.id != world.player.id]
            for d, vehicle in sorted(vehicles):
                if d > 200.0:
                    break
                vehicle_type = get_actor_display_name(vehicle, truncate=22)
                self._info_text.append('% 4dm %s' % (d, vehicle_type))

        speed = 3.6 * math.sqrt(v.x**2 + v.y**2 + v.z**2)
        throttle = c.throttle
        audiomanager.som(throttle, speed)  # teste

    def toggle_info(self):
        self._show_info = not self._show_info

    def notification(self, text, seconds=2.0):
        self._notifications.set_text(text, seconds=seconds)

    def error(self, text):
        self._notifications.set_text('Error: %s' % text, (255, 0, 0))

    def render(self, display):
        if self._show_info:
            info_surface = pygame.Surface((220, self.dim[1]))
            info_surface.set_alpha(100)
            display.blit(info_surface, (0, 0))
            v_offset = 4
            bar_h_offset = 100
            bar_width = 106
            for item in self._info_text:
                if v_offset + 18 > self.dim[1]:
                    break
                if isinstance(item, list):
                    if len(item) > 1:
                        points = [(x + 8, v_offset + 8 + (1.0 - y) * 30)
                                  for x, y in enumerate(item)]
                        pygame.draw.lines(
                            display, (255, 136, 0), False, points, 2)
                    item = None
                    v_offset += 18
                elif isinstance(item, tuple):
                    if isinstance(item[1], bool):
                        rect = pygame.Rect(
                            (bar_h_offset, v_offset + 8), (6, 6))
                        pygame.draw.rect(display, (255, 255, 255),
                                         rect, 0 if item[1] else 1)
                    else:
                        rect_border = pygame.Rect(
                            (bar_h_offset, v_offset + 8), (bar_width, 6))
                        pygame.draw.rect(
                            display, (255, 255, 255), rect_border, 1)
                        f = (item[1] - item[2]) / (item[3] - item[2])
                        if item[2] < 0.0:
                            rect = pygame.Rect(
                                (bar_h_offset + f * (bar_width - 6), v_offset + 8), (6, 6))
                        else:
                            rect = pygame.Rect(
                                (bar_h_offset, v_offset + 8), (f * bar_width, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect)
                    item = item[0]
                if item:  # At this point has to be a str.
                    surface = self._font_mono.render(
                        item, True, (255, 255, 255))
                    display.blit(surface, (8, v_offset))
                v_offset += 18
        self._notifications.render(display)
        self.help.render(display)



# ==============================================================================
# -- FadingText ----------------------------------------------------------------
# ==============================================================================


class FadingText(object):
    def __init__(self, font, dim, pos):
        self.font = font
        self.dim = dim
        self.pos = pos
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)

    def set_text(self, text, color=(255, 255, 255), seconds=2.0):
        text_texture = self.font.render(text, True, color)
        self.surface = pygame.Surface(self.dim)
        self.seconds_left = seconds
        self.surface.fill((0, 0, 0, 0))
        self.surface.blit(text_texture, (10, 11))

    def tick(self, _, clock):
        delta_seconds = 1e-3 * clock.get_time()
        self.seconds_left = max(0.0, self.seconds_left - delta_seconds)
        self.surface.set_alpha(500.0 * self.seconds_left)

    def render(self, display):
        display.blit(self.surface, self.pos)


# ==============================================================================
# -- HelpText ------------------------------------------------------------------
# ==============================================================================


class HelpText(object):
    def __init__(self, font, width, height):
        lines = __doc__.split('\n')
        self.font = font
        self.dim = (680, len(lines) * 22 + 12)
        self.pos = (0.5 * width - 0.5 *
                    self.dim[0], 0.5 * height - 0.5 * self.dim[1])
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)
        self.surface.fill((0, 0, 0, 0))
        for n, line in enumerate(lines):
            text_texture = self.font.render(line, True, (255, 255, 255))
            self.surface.blit(text_texture, (22, n * 22))
            self._render = False
        self.surface.set_alpha(220)

    def toggle(self):
        self._render = not self._render

    def render(self, display):
        if self._render:
            display.blit(self.surface, self.pos)


# ==============================================================================
# -- CollisionSensor -----------------------------------------------------------
# ==============================================================================

class CollisionSensor(object):
    def __init__(self, parent_actor, hud, logi_controller, steeringwheel):
        self.sensor = None
        self.history = []
        self._parent = parent_actor
        self.hud = hud
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.collision')
        self.sensor = world.spawn_actor(
            bp, carla.Transform(), attach_to=self._parent)
        self.steeringwheel = steeringwheel
        self.logi_controller = logi_controller

        # Carrega sons de colisão
        self.collision_sounds = [
            # Caminho para o primeiro som
            pygame.mixer.Sound(
                "./audio/CarCollision/hardcollision.wav"),
            # Caminho para o segundo som
            pygame.mixer.Sound(
                "./audio/CarCollision/lightcollision.wav")
        ]

        # Define volume (opcional)
        for sound in self.collision_sounds:
            sound.set_volume(0.7)

        # Inicializa o tempo da última colisão com som
        self.last_collision_time = 0
        self.collision_sound_cooldown = 2.0  # segundos

        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda event: CollisionSensor._on_collision(weak_self, event))

    def get_collision_history(self):
        history = collections.defaultdict(int)
        for frame, intensity in self.history:
            history[frame] += intensity
        return history

    @staticmethod
    def _on_collision(weak_self, event):
        self = weak_self()
        if not self:
            return
        
        if self.steeringwheel == True and self.logi_controller.is_connected(0):
            for i in range(5):
                self.logi_controller.LogiPlayFrontalCollisionForce(0, 13)
                self.logi_controller.logi_update()
                time.sleep(0.1)

        actor_type = get_actor_display_name(event.other_actor)
        self.hud.notification('Collision with %r' % actor_type)
        impulse = event.normal_impulse
        intensity = math.sqrt(impulse.x ** 2 + impulse.y ** 2 + impulse.z ** 2)
        self.history.append((event.frame, intensity))
        if len(self.history) > 4000:
            self.history.pop(0) 

        # ⏱️ Toca o som apenas se passou o tempo de cooldown
        current_time = time.time()
        if current_time - self.last_collision_time >= self.collision_sound_cooldown:
            sound_to_play = random.choice(self.collision_sounds)
            sound_to_play.play()
            self.last_collision_time = current_time



# ==============================================================================
# -- LaneInvasionSensor --------------------------------------------------------
# ==============================================================================


class LaneInvasionSensor(object):
    def __init__(self, parent_actor, hud):
        self.sensor = None
        self._parent = parent_actor
        self.hud = hud
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.lane_invasion')
        self.sensor = world.spawn_actor(
            bp, carla.Transform(), attach_to=self._parent)
        # We need to pass the lambda a weak reference to self to avoid circular
        # reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda event: LaneInvasionSensor._on_invasion(weak_self, event))

    @staticmethod
    def _on_invasion(weak_self, event):
        self = weak_self()
        if not self:
            return
        lane_types = set(x.type for x in event.crossed_lane_markings)
        text = ['%r' % str(x).split()[-1] for x in lane_types]
        self.hud.notification('Crossed line %s' % ' and '.join(text))

# ==============================================================================
# -- GnssSensor --------------------------------------------------------
# ==============================================================================


class GnssSensor(object):
    def __init__(self, parent_actor):
        self.sensor = None
        self._parent = parent_actor
        self.lat = 0.0
        self.lon = 0.0
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.gnss')
        self.sensor = world.spawn_actor(bp, carla.Transform(
            carla.Location(x=1.0, z=2.8)), attach_to=self._parent)
        # We need to pass the lambda a weak reference to self to avoid circular
        # reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda event: GnssSensor._on_gnss_event(weak_self, event))

    @staticmethod
    def _on_gnss_event(weak_self, event):
        self = weak_self()
        if not self:
            return
        self.lat = event.latitude
        self.lon = event.longitude
        
# ==============================================================================
# -- LidarSensor
# ==============================================================================

class LidarSensor(object):
    def __init__(self, parent_actor):
        self.sensor = None
        self._parent = parent_actor
        self.data = None
        self.points = np.zeros((0, 3))

        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.lidar.ray_cast')
        bp.set_attribute("role_name", "front/lidar")
        bp.set_attribute('channels', '128')
        bp.set_attribute('range', '200.0')
        bp.set_attribute('points_per_second', '300000')
        bp.set_attribute('upper_fov', '10.0')
        bp.set_attribute('lower_fov', '-30.0')

        lidar_transform = carla.Transform(
	    carla.Location(x=177.7, y=105.6, z=16.7),
            carla.Rotation(pitch=-10.0, yaw=53.0, roll=-2.5))
        self.sensor = world.spawn_actor(bp, lidar_transform)

        weak_self = weakref.ref(self)
        self.sensor.listen(lambda data: LidarSensor._on_lidar_event(weak_self, data))

    @staticmethod
    def _on_lidar_event(weak_self, data):
        self = weak_self()
        if not self:
            return

        raw = np.frombuffer(data.raw_data, dtype=np.float32)

        if raw.size == 0:
            # No points this frame — skip safely
            return

        # Determine how many floats per point (4 or 6)
        if raw.size % 6 == 0:
            pts = raw.reshape((-1, 6))
        elif raw.size % 4 == 0:
            pts = raw.reshape((-1, 4))
        else:
            # Unexpected or corrupted frame, skip it
            print(f"[WARN] Unexpected LiDAR data length: {raw.size}")
            return

        self.points = pts[:, :3]
    
    def destroy(self):
        if self.sensor is not None:
            self.sensor.stop()
            self.sensor.destroy()
            self.sensor = None


# ==============================================================================
# -- CameraInfra
# ==============================================================================

class CameraInfra(object):

    def __init__(self, parent_actor, hud):
        self.sensor = None
        self.surface = None
        self._parent = parent_actor
        self.recording = False
        self.hud = hud

        self.transform = carla.Transform(
            carla.Location(x=177.7, y=105.6, z=16.7),
            carla.Rotation(pitch=-10.0, yaw=53.0, roll=-2.5)
        )

        self._spawn_sensor()

    def _spawn_sensor(self):
        world = self._parent.get_world()
        bp_library = world.get_blueprint_library()

        bp = bp_library.find("sensor.camera.rgb")
        bp.set_attribute("role_name", "infra_rgb")
        bp.set_attribute("image_size_x", str(self.hud.dim[0]))
        bp.set_attribute("image_size_y", str(self.hud.dim[1]))
        bp.set_attribute("fov", "115")

        self.sensor = world.spawn_actor(bp, self.transform)

        weak_self = weakref.ref(self)
        self.sensor.listen(lambda img: CameraInfra._parse_image(weak_self, img))

        self.hud.notification("Infra Camera Activated")

    def destroy(self):
        if self.sensor:
            self.sensor.stop()
            self.sensor.destroy()
            self.sensor = None
            self.hud.notification("Infra Camera Destroyed")

    def toggle_recording(self):
        self.recording = not self.recording
        self.hud.notification(f"Infra Recording {'ON' if self.recording else 'OFF'}")

    def render(self, display):
        if self.surface is not None:
            display.blit(self.surface, (0, 0))

    @staticmethod
    def _parse_image(weak_self, image):
        self = weak_self()
        if not self:
            return

        # Always Raw conversion since it's RGB
        image.convert(cc.Raw)

        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = np.reshape(array, (image.height, image.width, 4))
        array = array[:, :, :3]
        array = array[:, :, ::-1]  # BGR → RGB

        self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))

        if self.recording:
            image.save_to_disk(f'_out_infra/{image.frame:08d}')


# ==============================================================================
# -- CameraManager
# ==============================================================================


class CameraManager(object):
    def __init__(self, parent_actor, hud, steeringwheel):
        self.sensor = None
        self.surface = None
        self._parent = parent_actor
        self.hud = hud
        self.recording = False
        self.steeringwheel = steeringwheel
        self._camera_transforms = [
            carla.Transform(carla.Location(x=-0.4, y=-0.40, z=1.40),
                            carla.Rotation(pitch=-4, yaw=9, roll=-1.5)),
            carla.Transform(carla.Location(x=-6.5, z=2.8),
                            carla.Rotation(pitch=-15)),
            carla.Transform(carla.Location(x=1.6, z=1.7)), # front
            carla.Transform(carla.Location(x=0.4, z=1.8),
                            carla.Rotation(pitch=-15)),
        ]

        self.transform_index = 1
        self.sensors = [
            ['sensor.camera.rgb', cc.Raw, 'Camera RGB'],
            ['sensor.camera.depth', cc.Raw, 'Camera Depth (Raw)'],
            ['sensor.camera.depth', cc.Depth, 'Camera Depth (Gray Scale)'],
            ['sensor.camera.depth', cc.LogarithmicDepth,
                'Camera Depth (Logarithmic Gray Scale)'],
            ['sensor.camera.semantic_segmentation', cc.Raw,
                'Camera Semantic Segmentation (Raw)'],
            ['sensor.camera.semantic_segmentation', cc.CityScapesPalette,
                'Camera Semantic Segmentation (CityScapes Palette)']]
        world = self._parent.get_world()
        bp_library = world.get_blueprint_library()
        for item in self.sensors:
            bp = bp_library.find(item[0])
            if item[0].startswith('sensor.camera'):
                bp.set_attribute('fov', '115')  # teste fov
                bp.set_attribute('image_size_x', str(hud.dim[0]))
                bp.set_attribute('image_size_y', str(hud.dim[1]))
            item.append(bp)
        self.index = None

    def move_x(self):
        self._camera_transforms[0].set_transform(x=1, y=2, z=3)

    def toggle_camera(self):
        self.transform_index = (self.transform_index +
                                1) % len(self._camera_transforms)
        self.sensor.set_transform(
            self._camera_transforms[self.transform_index])

    def set_sensor(self, index, notify=True):
        index = index % len(self.sensors)
        needs_respawn = True if self.index is None \
            else self.sensors[index][0] != self.sensors[self.index][0]
        if needs_respawn:
            if self.sensor is not None:
                self.sensor.destroy()
                self.surface = None
            self.sensor = self._parent.get_world().spawn_actor(
                self.sensors[index][-1],
                self._camera_transforms[2] if self.steeringwheel == False and 'rgb' in self.sensors[index][-1].id \
                    else self._camera_transforms[self.transform_index],
                attach_to=self._parent)
            # We need to pass the lambda a weak reference to self to avoid
            # circular reference.
            weak_self = weakref.ref(self)
            self.sensor.listen(
                lambda image: CameraManager._parse_image(weak_self, image))
        if notify:
            self.hud.notification(self.sensors[index][2])
        self.index = index

    def next_sensor(self):
        self.set_sensor(self.index + 1)

    def toggle_recording(self):
        self.recording = not self.recording
        self.hud.notification('Recording %s' %
                              ('On' if self.recording else 'Off'))

    def render(self, display):
        if self.surface is not None:
            display.blit(self.surface, (0, 0))

    @staticmethod
    def _parse_image(weak_self, image):
        self = weak_self()
        if not self:
            return
        image.convert(self.sensors[self.index][1])
        array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
        array = np.reshape(array, (image.height, image.width, 4))
        array = array[:, :, :3]
        array = array[:, :, ::-1]
        self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
        if self.recording:
            image.save_to_disk('_out/%08d' % image.frame)


def is_close(pos1, pos2, forward_vector, threshold=30.0):

    dx = pos1.x - pos2.x
    dy = pos1.y - pos2.y

    distance_2d = (dx ** 2 + dy ** 2) ** 0.5
    is_within_threshold = distance_2d <= threshold

    relative_vector = pos2 - pos1
    dot_product = forward_vector.dot(relative_vector)

    return is_within_threshold, dot_product

# ==============================================================================
# -- SocketSender() --------------------------------------------------------------------
# ==============================================================================

class SocketSender:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.listen_sock = None
        self.clients = []  # List to store active client socket objects
        self.running = True
        self.log_file = "v2x_sent_log.csv"
        
        # Initialize CSV log with header
        if not os.path.exists(self.log_file):
            with open(self.log_file, "w") as f:
                f.write("timestamp,msg_cnt,msg_type,seq\n")

    def start_server(self):
        """Initializes the server with IPv6 Dual-Stack support."""
        # Use AF_INET6 for dual-stack support
        self.listen_sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            # Enable dual-stack: accept both IPv4 and IPv6
            self.listen_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, socket.error):
            # Fallback if IPv6_V6ONLY is not supported
            pass
            
        self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind to '::' to accept both IPv4 and IPv6
        self.listen_sock.bind(('::', self.port))
        self.listen_sock.listen(5)
        print(f"[INFO] Server listening on [::]:{self.port} (Dual-Stack)...")

        # Start the background thread for accepting connections
        self.accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        self.accept_thread.start()

    def _accept_clients(self):
        """Background loop to accept new clients without blocking the main game."""
        while self.running:
            try:
                client_sock, addr = self.listen_sock.accept()
                print(f"[INFO] New client connected from: {addr}")
                self.clients.append(client_sock)
            except Exception as e:
                if self.running:
                    print(f"[ERROR] Accept failed: {e}")
                break

    def _extract_msg_cnt(self, data):
        """Recursively search for msgCnt in the J2735 message structure."""
        if isinstance(data, dict):
            if "msgCnt" in data:
                return data["msgCnt"]
            for v in data.values():
                res = self._extract_msg_cnt(v)
                if res is not None: return res
        elif isinstance(data, list):
            for item in data:
                res = self._extract_msg_cnt(item)
                if res is not None: return res
        return None

    def send_event(self, event_data, seq=None):
        """Sends data to ALL connected clients and removes dead ones."""
        if not self.clients:
            return

        t_sent = time.time()
        # Inject metrics metadata for RSU/MEC consumption
        if isinstance(event_data, dict):
            event_data["_ts"] = t_sent
            if seq is not None:
                event_data["_seq"] = seq

            # Extract msgCnt for local correlation log
            msg_cnt = self._extract_msg_cnt(event_data)
            msg_type = list(event_data.keys())[0] if event_data else "unknown"

            # Log to CSV
            try:
                with open(self.log_file, "a") as f:
                    f.write(f"{t_sent},{msg_cnt if msg_cnt is not None else -1},{msg_type},{seq if seq is not None else -1}\n")
            except Exception as e:
                print(f"[ERROR] Failed to log metrics: {e}")

        message = json.dumps(event_data).encode('utf-8') + b'\n'
        disconnected_clients = []

        for client in self.clients:
            try:
                client.sendall(message)
            except (socket.error, BrokenPipeError):
                disconnected_clients.append(client)

        # Clean up clients that closed the connection
        for client in disconnected_clients:
            print("[INFO] Removing disconnected client.")
            client.close()
            self.clients.remove(client)

    def close(self):
        self.running = False
        if self.listen_sock:
            self.listen_sock.close()
        for client in self.clients:
            client.close()
        print("[INFO] Server shut down.")

# ==============================================================================
# -- UDPSender() (5G Slice Path) -----------------------------------------------
# ==============================================================================

class UDPSender:
    """Sends V2X messages via UDP for the 5G network slice path.
    This is the parallel path alongside the TCP SocketSender (C-V2X).
    Messages are sent to the RSU 5G Forwarder or directly to the OBU on the 5G slice."""

    def __init__(self, target_ip, target_port=9090):
        self.target_ip = target_ip
        self.target_port = target_port
        
        # Determine address family (IPv4 or IPv6)
        try:
            addr_info = socket.getaddrinfo(target_ip, target_port, socket.AF_UNSPEC, socket.SOCK_DGRAM)
            family = addr_info[0][0]
            self.target_addr = addr_info[0][4]
        except Exception:
            family = socket.AF_INET
            self.target_addr = (target_ip, target_port)

        self.sock = socket.socket(family, socket.SOCK_DGRAM)
        self.msg_count = 0
        self.enabled = True
        print(f"[5G] UDPSender initialized → {target_ip}:{target_port} (Family: {'IPv6' if family == socket.AF_INET6 else 'IPv4'})")

    def send_event(self, event_data, seq=None):
        """Sends V2X JSON data via UDP to the 5G path."""
        if not self.enabled:
            return
        
        # Inject metrics metadata
        if isinstance(event_data, dict):
            event_data["_ts"] = time.time()
            if seq is not None:
                event_data["_seq"] = seq

        try:
            message = json.dumps(event_data).encode('utf-8') + b'\n'
            self.sock.sendto(message, self.target_addr)
            self.msg_count += 1
        except Exception as e:
            print(f"[5G] UDP send error: {e}")

    def close(self):
        self.enabled = False
        self.sock.close()
        print(f"[5G] UDPSender closed. Total msgs sent: {self.msg_count}")

# Global mapping structure for precise real-world coords
_df_carla = None
_df_obu = None
_nn_xy = None
_nn_latlon = None
_mapping_loaded = False

def _load_coordinates_mapping():
    global _df_carla, _df_obu, _nn_xy, _nn_latlon, _mapping_loaded
    _mapping_loaded = True
    if pd is None or NearestNeighbors is None:
        print("[WARN] pandas ou sklearn não instalados. O snap de coordenadas duplas não funcionará.")
        return
    try:
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_carla_path = os.path.join(base_dir, 'coordinates.csv')
        csv_obu_path = os.path.join(base_dir, 'coordinates_obu.csv')
        
        if not os.path.exists(csv_carla_path): csv_carla_path = 'coordinates.csv'
        if not os.path.exists(csv_obu_path): csv_obu_path = 'coordinates_obu.csv'
            
        _df_carla = pd.read_csv(csv_carla_path, header=None)
        _df_carla.columns = ['lat', 'lon', 'x', 'y', 'yaw']
        _nn_xy = NearestNeighbors(n_neighbors=1, algorithm='ball_tree')
        _nn_xy.fit(_df_carla[['x', 'y']].values)

        _df_obu = pd.read_csv(csv_obu_path, header=None)
        _df_obu.columns = ['lat_10u', 'lon_10u', 'elev', 'heading']
        _df_obu['lat'] = _df_obu['lat_10u'] / 10000000.0
        _df_obu['lon'] = _df_obu['lon_10u'] / 10000000.0
        
        _nn_latlon = NearestNeighbors(n_neighbors=1, algorithm='ball_tree')
        _nn_latlon.fit(_df_obu[['lat', 'lon']].values)
        
        print("[INFO] Carregados coordinates.csv e coordinates_obu.csv para snap cruzado de coordenadas!")
    except Exception as e:
        print(f"[WARN] Falha ao carregar CSVs para snap cruzado: {e}")

def carla_location_to_wgs84(location):
    global _df_carla, _df_obu, _nn_xy, _nn_latlon, _mapping_loaded
    if not _mapping_loaded:
        _load_coordinates_mapping()
        
    if _df_carla is not None and _df_obu is not None and _nn_xy is not None and _nn_latlon is not None:
        # 1. Mapeia o (x,y) do CARLA para a latitude/longitude projetada mais próxima no arquivo coordinates.csv
        dist_xy, idx_xy = _nn_xy.kneighbors([[location.x, location.y]])
        nearest_carla = _df_carla.iloc[idx_xy[0][0]]
        
        # 2. Busca a coordenada real da OBU que é geometricamente mais próxima da coordenada CARLA projetada
        dist_ll, idx_ll = _nn_latlon.kneighbors([[nearest_carla['lat'], nearest_carla['lon']]])
        nearest_obu = _df_obu.iloc[idx_ll[0][0]]
        
        return nearest_obu['lat'], nearest_obu['lon']
    else:
        # Fallback to simple flat earth offset
        lat = -23.4703361 + (location.y / 111139)
        lon = -47.4308804 + (location.x / (111139 * math.cos(math.radians(lat))))
        return lat, lon


def generate_psm(pedestrian, history_buffer, reference_lat, reference_lon, reference_elev, msg_count=0):
    """
    Generate a PSM JSON for a CARLA pedestrian actor.

    Args:
        pedestrian (carla.Actor): Pedestrian actor.
        history_buffer (list): List of dicts with historical positions.
        reference_lat (float): WGS84 latitude reference.
        reference_lon (float): WGS84 longitude reference.
        reference_elev (float): Reference elevation (m).
        msg_count (int): Message counter (0–127).

    Returns:
        dict: Full PSM message.
    """
    transform = pedestrian.get_transform()
    
    # Optional fallback if CARLA velocity is 0
    raw_velocity = pedestrian.get_velocity()
    
    # Convert location to WGS84 (lat/lon)
    lat, lon = carla_location_to_wgs84(transform.location)

    actor_id_hex = format(pedestrian.id, '08X')[:8]
    now = time.time()
    sec_mark = int((now * 1000) % 60000)
    
    # Elev in decimeters (10cm units) for J2735
    elev_j2735 = int(transform.location.z * 10)

    # --- Dynamic Speed & Heading Calculation fallback ---
    # CARLA walkers sometimes return (0,0,0) for get_velocity() when controlled by AI scripts
    # We will derive it using position delta over time
    ped_id = pedestrian.id
    if not hasattr(generate_psm, '_prev_states'):
        generate_psm._prev_states = {}

    speed = 0
    heading = 0

    if ped_id in generate_psm._prev_states:
        prev_state = generate_psm._prev_states[ped_id]
        dt = now - prev_state['time']
        
        if dt > 0.001:
            # Calculate dx, dy in world coordinates
            dx = transform.location.x - prev_state['x']
            dy = transform.location.y - prev_state['y']
            dz = transform.location.z - prev_state['z']
            
            # Speed in m/s
            speed_ms = math.sqrt(dx**2 + dy**2 + dz**2) / dt
            speed = min(8191, int(speed_ms * 50)) # J2735: 0.02 m/s
            
            # Heading in degrees
            yaw_deg = math.degrees(math.atan2(dy, dx))
            if yaw_deg < 0: yaw_deg += 360.0
            heading = int(yaw_deg / 0.0125) % 28800 # J2735: 0.0125 deg

            # If the pedestrian is standing perfectly still, preserve last known heading
            if speed_ms < 0.1:
                heading = prev_state['heading']
    else:
        # Fallback to CARLA velocity if first frame (might be zero)
        speed_ms = math.sqrt(raw_velocity.x**2 + raw_velocity.y**2 + raw_velocity.z**2)
        speed = min(8191, int(speed_ms * 50))
        yaw = transform.rotation.yaw
        if yaw < 0: yaw += 360.0
        heading = int(yaw / 0.0125) % 28800

    # Store current state
    generate_psm._prev_states[ped_id] = {
        'x': transform.location.x,
        'y': transform.location.y,
        'z': transform.location.z,
        'time': now,
        'heading': heading
    }

    psm = {
        "psm": {
            "messageId": 32,
            "value": {
                "basicType": "aPEDESTRIAN",
                "secMark": sec_mark,
                "msgCnt": msg_count % 128,
                "id": actor_id_hex,
                "position": {
                    "lat": int(lat * 1e7),
                    "long": int(lon * 1e7),
                    "elevation": elev_j2735
                },
                "accuracy": {
                    "semiMajor": 40,
                    "semiMinor": 40,
                    "orientation": 0
                },
                "speed": speed,
                "heading": heading,
                "pathHistory": {
                    "crumbData": [
                        {
                            "latOffset": int((entry["lat"] - reference_lat) * 1e7),
                            "lonOffset": int((entry["lon"] - reference_lon) * 1e7),
                            "elevationOffset": int((entry["elev"] - reference_elev) * 10),
                            "timeOffset": entry["timeOffset"]
                        }
                        for entry in history_buffer
                    ]
                },
                "pathPrediction": {
                    "radiusOfCurve": 0,
                    "confidence": 200
                }
            }
        }
    }

    return psm

def generate_bsm(vehicle, msg_count=0):
    """
    Generate a BSM JSON for the ego vehicle.
    Includes dynamic acceleration derived from velocity delta between frames.
    """
    transform = vehicle.get_transform()
    velocity = vehicle.get_velocity()
    control = vehicle.get_control()
    
    # Convert location to WGS84 (1/10 microdegrees)
    lat, lon = carla_location_to_wgs84(transform.location)
    lat_10u = int(lat * 10_000_000)
    lon_10u = int(lon * 10_000_000)
    
    # CARLA Elev is meters. J2735 is units of 10 cm
    elev = int(transform.location.z * 10)
    
    # ID: 8 hex chars
    actor_id_hex = format(vehicle.id, '08X')[:8]
    
    # secMark: Modulo 60000 milliseconds
    now = time.time()
    sec_mark = int((now * 1000) % 60000)
    
    # Speed: 0.02 m/s units. CARLA vel is m/s
    speed_ms = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
    speed_j2735 = int(speed_ms * 50)
    
    # Heading: 0.0125 degrees units. CARLA yaw is degrees.
    yaw = transform.rotation.yaw
    if yaw < 0:
        yaw += 360.0
    heading_j2735 = int(yaw / 0.0125) % 28800
    
    # Steering Wheel Angle limit to J2735
    steer = int(control.steer * 127)
    
    # --- Dynamic Acceleration Calculation ---
    # J2735 units: long/lat = 0.01 m/s², vert = 0.02 G, yaw = 0.01 deg/s
    accel_long_j2735 = 0
    accel_lat_j2735 = 0
    accel_vert_j2735 = 0
    yaw_rate_j2735 = 0

    if not hasattr(generate_bsm, '_prev_state'):
        generate_bsm._prev_state = {}

    prev = generate_bsm._prev_state.get(vehicle.id)
    if prev is not None:
        dt = now - prev['time']
        if dt > 0.001:  # Avoid division by near-zero
            # Raw acceleration in m/s² (world frame)
            ax = (velocity.x - prev['vx']) / dt
            ay = (velocity.y - prev['vy']) / dt
            az = (velocity.z - prev['vz']) / dt

            # Decompose into longitudinal (along heading) and lateral (perpendicular)
            yaw_rad = math.radians(transform.rotation.yaw)
            forward_x = math.cos(yaw_rad)
            forward_y = math.sin(yaw_rad)

            # Longitudinal = dot(accel, forward)
            accel_long = ax * forward_x + ay * forward_y
            # Lateral = cross(forward, accel) — positive = left
            accel_lat = -ax * forward_y + ay * forward_x

            # Convert to J2735 units and clamp
            accel_long_j2735 = max(-2000, min(2001, int(accel_long * 100)))
            accel_lat_j2735 = max(-2000, min(2001, int(accel_lat * 100)))
            # Vertical: units of 0.02 G (1G = 9.81 m/s²)
            accel_vert_j2735 = max(-127, min(127, int(az / (9.81 * 0.02))))

            # Yaw rate: degrees/second in 0.01 deg/s units
            delta_yaw = transform.rotation.yaw - prev['yaw']
            # Normalize to [-180, 180]
            if delta_yaw > 180: delta_yaw -= 360
            if delta_yaw < -180: delta_yaw += 360
            yaw_rate = delta_yaw / dt
            yaw_rate_j2735 = max(-32767, min(32767, int(yaw_rate * 100)))

    # Store current state for next frame
    generate_bsm._prev_state[vehicle.id] = {
        'time': now,
        'vx': velocity.x,
        'vy': velocity.y,
        'vz': velocity.z,
        'yaw': transform.rotation.yaw
    }

    bsm = {
        "bsm": {
            "messageId": 20,
            "value": {
                "coreData": {
                    "msgCnt": msg_count % 128,
                    "id": actor_id_hex,
                    "secMark": sec_mark,
                    "lat": lat_10u,
                    "long": lon_10u,
                    "elev": elev,
                    "accuracy": {
                        "semiMajor": 40,
                        "semiMinor": 40,
                        "orientation": 0
                    },
                    "transmission": "forwardGears",
                    "speed": speed_j2735,
                    "heading": heading_j2735,
                    "angle": steer,
                    "accelSet": {
                        "long": accel_long_j2735,
                        "lat": accel_lat_j2735,
                        "vert": accel_vert_j2735,
                        "yaw": yaw_rate_j2735
                    },
                    "brakes": {
                        "wheelBrakes": "10" if control.brake > 0 else "00",
                        "traction": "unavailable",
                        "abs": "unavailable",
                        "scs": "unavailable",
                        "brakeBoost": "unavailable",
                        "auxBrakes": "unavailable"
                    },
                    "size": {
                        "width": 200,
                        "length": 500
                    }
                }
            }
        }
    }
    return bsm

def generate_rsa(msg_count=0):
    """
    Generate a dynamic Road Side Alert (RSA) JSON.
    """
    return {
        "rsa": {
            "messageId": 27,
            "value": {
                "msgCnt": msg_count % 128,
                "typeEvent": 1231, # Collision
                "description": [533],
                "priority": "00",
                "heading": {
                    "value": "0001",
                    "length": 16
                },
                "extent": "useInstantlyOnly",
                "position": {
                    "long": -474300000,
                    "lat": -234705000,
                    "elevation": 100
                },
                "furtherInfoID": "0000"
            }
        }
    }

def generate_tim(msg_count=0):
    """
    Generate a dynamic Traveler Information Message (TIM) JSON.
    """
    return {
        "tim": {
            "messageId": 31,
            "value": {
                "msgCnt": msg_count % 127,
                "timeStamp": int(time.time() % 525600),
                "packetID": "000000000000000000",
                "dataFrames": [
                    {
                        "notUsed": 0,
                        "frameType": "advisory",
                        "msgId": {
                            "roadSignID": {
                                "position": {
                                    "lat": -234710000,
                                    "long": -474290000,
                                    "elevation": 100
                                },
                                "viewAngle": "0000",
                                "mutcdCode": "warning",
                                "crc": "0000"
                            }
                        },
                        "startTime": 0,
                        "durationTime": 1,
                        "priority": 1,
                        "notUsed1": 0,
                        "regions": [
                            {
                                "name": "zona_escolar",
                                "anchor": {
                                    "lat": -234710000,
                                    "long": -474290000,
                                    "elevation": 100
                                },
                                "directionality": "both",
                                "closedPath": False
                            }
                        ],
                        "notUsed2": 0,
                        "notUsed3": 0,
                        "content": {
                            "workZone": [
                                {"item": {"itis": 4867}}
                            ]
                        }
                    }
                ]
            }
        }
    }

GLOBAL_MAP_CACHE = None

MAX_LANES_PER_INTERSECTION = 10  # Limit to keep JSON under 16 KB
MAX_NODES_PER_LANE = 10

def load_map_cache(file_path=None):
    """Load map_cruzamento.json into global cache (once)."""
    global GLOBAL_MAP_CACHE
    if GLOBAL_MAP_CACHE is not None:
        return True
    if file_path is None:
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map_cruzamento.json")
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                GLOBAL_MAP_CACHE = json.load(f)
            print(f"[INFO] MAP file loaded and cached.")
            return True
    except Exception as e:
        print(f"[ERROR] Failed to load MAP: {e}")
    return False

def generate_map_for_intersection(intersection_id, msg_count=0):
    """
    Build a MAP payload containing ONLY the intersection with the given ID.
    Limits lanes and nodes to keep the JSON under 16 KB (fact_alert.c buffer).
    """
    if GLOBAL_MAP_CACHE is None or "mapData" not in GLOBAL_MAP_CACHE:
        return None

    intersections = GLOBAL_MAP_CACHE["mapData"]["value"]["intersections"]
    target = None
    for inter in intersections:
        if inter["id"]["id"] == intersection_id:
            target = inter
            break

    if target is None:
        return None

    # Deep-copy and trim the intersection to fit in 16 KB
    import copy
    trimmed = copy.deepcopy(target)

    # Limit lanes
    if "laneSet" in trimmed and len(trimmed["laneSet"]) > MAX_LANES_PER_INTERSECTION:
        trimmed["laneSet"] = trimmed["laneSet"][:MAX_LANES_PER_INTERSECTION]

    # Limit nodes per lane
    for lane in trimmed.get("laneSet", []):
        nodes = lane.get("nodeList", {}).get("nodes", [])
        if len(nodes) > MAX_NODES_PER_LANE:
            lane["nodeList"]["nodes"] = nodes[:MAX_NODES_PER_LANE]

    # Remove optional heavy fields
    trimmed.pop("speedLimits", None)

    return {
        "mapData": {
            "messageId": 18,
            "value": {
                "msgIssueRevision": msg_count % 128,
                "intersections": [trimmed]
            }
        }
    }

def generate_spat(intersection_id, active_phases, msg_count=0):
    """
    Generate a Signal Phase and Timing (SPAT) JSON for a specific intersection.
    active_phases is a dict of {signalGroup_id (int): event_state (str)}
    """
    now = time.time()
    local_time = time.localtime(now)
    current_dsec = int((local_time.tm_min * 60 + local_time.tm_sec) * 10)

    states_list = []
    for sg_id, state in active_phases.items():
        states_list.append({
            "signalGroup": sg_id,
            "state-time-speed": [
                {
                    "eventState": state,
                    "timing": {
                        "minEndTime": (current_dsec + 100) % 36000,
                        "maxEndTime": (current_dsec + 150) % 36000
                    }
                }
            ]
        })

    return {
        "spat": {
            "messageId": 19,
            "value": {
                "intersections": [
                    {
                        "id": {
                            "region": 0,
                            "id": intersection_id
                        },
                        "revision": 1,
                        "status": "0000",
                        "states": states_list
                    }
                ]
            }
        }
    }

# ==============================================================================
# -- game_loop() ---------------------------------------------------------------
# ==============================================================================


def game_loop(args, logi_controller):
    pygame.init()
    pygame.font.init()
    world = None
    sender = None
    sender_5g = None

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(20.0)

        display = pygame.display.set_mode(
            (args.width, args.height),
            pygame.HWSURFACE | pygame.DOUBLEBUF)

        hud = HUD(args.width, args.height)
        print("\n[INFO] Carregando mundo e veículos no CARLA... Aguarde alguns segundos!\n")
        print("[DEBUG] Calling client.get_world()...")
        carla_world = client.get_world()
        print("[DEBUG] Starting World init...")
        world = World(carla_world, hud, args.filter, logi_controller, args.steeringwheel)
        print("[DEBUG] Starting DualControl init...")
        controller = DualControl(world, args.autopilot, args.steeringwheel)

        clock = pygame.time.Clock()
        
        if args.steeringwheel == True:
            # Inicializa o volante
            print("[DEBUG] Calling steering_initialize()...")
            if logi_controller.steering_initialize():
                print("Volante inicializado com sucesso.")
                # Verifica a conexão
                if logi_controller.is_connected(0):
                    print("Volante detectado.")
                    for i in range(2):
                        logi_controller.LogiPlaySpringForce(0, 1, 30, 50)
                        logi_controller.logi_update()
                        time.sleep(0.1)

        HOST = "0.0.0.0"
        PORT = 8080

        sender = SocketSender(HOST, PORT)
        sender.start_server()

        # --- 5G Slice Path (Descoberta automática via DDNS) ---
        # 1. Se o usuário passou --v2x-5g-ip, usa direto
        # 2. Senão, lê v2x_ddns.conf e consulta o servidor DDNS automaticamente
        v2x_5g_ip = args.v2x_5g_ip
        v2x_5g_port = args.v2x_5g_port

        if not v2x_5g_ip:
            # Auto-discovery: lê v2x_ddns.conf → consulta DDNS → obtém IP do RSU
            discovered_ip, discovered_port = auto_discover_rsu()
            if discovered_ip:
                v2x_5g_ip = discovered_ip
                v2x_5g_port = discovered_port
            
        if v2x_5g_ip:
            sender_5g = UDPSender(v2x_5g_ip, v2x_5g_port)
            print(f"[5G] Dual-path ENABLED: C-V2X (TCP:{PORT}) + 5G (UDP:{v2x_5g_ip}:{v2x_5g_port})")
        else:
            print(f"[INFO] Single-path: C-V2X only (TCP:{PORT}). RSU não encontrado no DDNS.")
            print(f"[INFO] Edite v2x_ddns.conf com o endereço do servidor DDNS ou use --v2x-5g-ip.")

        msg_cnt = 0

        # WGS84 Coords for alert zones
        RSA_ZONE_LAT = -23.4705
        RSA_ZONE_LON = -47.4300
        TIM_ZONE_LAT = -23.4710
        TIM_ZONE_LON = -47.4290
        TRIGGER_RADIUS_DEG = 0.0008 # ~80 meters for better high-speed capture
        STILL_THRESHOLD = 0.000001 # ~10cm

        last_run = 0
        last_car_pos = (0, 0)
        delay = 0.1 # 10Hz V2X Standard frequency
        while True:
            client.get_world().wait_for_tick()
            clock.tick_busy_loop(0) #fps client
            if controller.parse_events(world, clock):
                return
            world.tick(clock)
            world.render(display)
            pygame.display.flip()

            current_time = time.time()
            if current_time - last_run > delay:
                # 0. Sync and initialize
                last_run = current_time
                if world is None or world.player is None:
                    continue
                    
                psm_msg = None
                tim_msg = None
                rsa_msg = None
                map_msg = None
                spat_msg = None
                
                # 1. ALWAYS generate BSMs for the Host Vehicle and all nearby vehicles
                bsm_msgs = []
                car_lat = 0
                car_lon = 0
                
                ego_transform = world.player.get_transform()
                all_vehicles = client.get_world().get_actors().filter('vehicle.*')
                
                for v in all_vehicles:
                    # Ignore vehicles farther than 500m
                    if v.get_transform().location.distance(ego_transform.location) < 500.0:
                        bsm = generate_bsm(v, msg_count=msg_cnt)
                        if bsm:
                            bsm_msgs.append(bsm)
                            # Use ego vehicle's location as reference for Map/Geofenced messages
                            if v.id == world.player.id:
                                car_lat = bsm["bsm"]["value"]["coreData"]["lat"] / 10000000.0
                                car_lon = bsm["bsm"]["value"]["coreData"]["long"] / 10000000.0
                
                # Check for Geographic Alert Zones using Ego location
                
                # Check for stillness
                dist_moved = math.sqrt((car_lat - last_car_pos[0])**2 + (car_lon - last_car_pos[1])**2)
                is_stationary = dist_moved < STILL_THRESHOLD
                last_car_pos = (car_lat, car_lon)

                # Broadcast optional messages only if moved or every 2s if stationary
                if not is_stationary or msg_cnt % 20 == 0:
                    # 2a. TIM/RSA (Geofenced placeholders)
                    dist_rsa = math.sqrt((car_lat - RSA_ZONE_LAT)**2 + (car_lon - RSA_ZONE_LON)**2)
                    if dist_rsa < TRIGGER_RADIUS_DEG:
                        rsa_msg = generate_rsa(msg_count=msg_cnt)
                    
                    dist_tim = math.sqrt((car_lat - TIM_ZONE_LAT)**2 + (car_lon - TIM_ZONE_LON)**2)
                    if dist_tim < TRIGGER_RADIUS_DEG:
                        tim_msg = generate_tim(msg_count=msg_cnt)

                    # 2b. DYNAMIC MAP & SPAT (Topology-aware)
                    # Load map to intersections if not done
                    if GLOBAL_MAP_CACHE is None:
                        load_map_cache(file_path=args.map_file)
                    
                    if GLOBAL_MAP_CACHE and "mapData" in GLOBAL_MAP_CACHE:
                        intersections = GLOBAL_MAP_CACHE["mapData"]["value"]["intersections"]
                        for inter in intersections:
                            ref = inter["refPoint"]
                            inter_lat = ref["lat"] / 10000000.0
                            inter_lon = ref["long"] / 10000000.0
                            inter_id = inter["id"]["id"]

                            dist_inter = math.sqrt((car_lat - inter_lat)**2 + (car_lon - inter_lon)**2)
                            if dist_inter < TRIGGER_RADIUS_DEG:
                                # Car is near this intersection -> Send MAP (single intersection only)
                                if msg_cnt % 10 == 0: # 1Hz for MAP
                                    map_msg = generate_map_for_intersection(inter_id, msg_count=msg_cnt)
                                
                                # Find all traffic lights near this intersection to update SPaT
                                try:
                                    traffic_lights = client.get_world().get_actors().filter('traffic.traffic_light')
                                    active_phases = {}
                                    
                                    for tl in traffic_lights:
                                        tl_loc = tl.get_transform().location
                                        tl_lat, tl_lon = carla_location_to_wgs84(tl_loc)
                                        dist_tl = math.sqrt((tl_lat - inter_lat)**2 + (tl_lon - inter_lon)**2)
                                        
                                        # Use a slightly larger radius for traffic lights
                                        if dist_tl < TRIGGER_RADIUS_DEG * 1.5:
                                            # Generate a J2735 signalGroup ID (1-255) from the Carla Actor ID
                                            sg_id = (tl.id % 254) + 1
                                            
                                            state_map = {
                                                carla.TrafficLightState.Red: "stop-And-Remain",
                                                carla.TrafficLightState.Yellow: "protected-clearance",
                                                carla.TrafficLightState.Green: "protected-Movement-Allowed",
                                                carla.TrafficLightState.Off: "unavailable",
                                                carla.TrafficLightState.Unknown: "unavailable"
                                            }
                                            active_phases[sg_id] = state_map.get(tl.get_state(), "unavailable")
                                    
                                    if active_phases:
                                        spat_msg = generate_spat(inter_id, active_phases, msg_cnt)
                                except Exception as e:
                                    print(f"Error extracting SPaT: {e}")
                                break # Trigger for nearest intersection found

                # 3. Check for Pedestrian Collisions (PSM)
                vehicles = client.get_world().get_actors().filter('vehicle.*')
                walkers = client.get_world().get_actors().filter('walker.*')
                
                psm_generated = False
                for vehicle in vehicles:
                    if psm_generated: break
                    for walker in walkers:
                        vehicle_transform = vehicle.get_transform()
                        forward_vec = vehicle_transform.get_forward_vector()
                        vehicle_loc = vehicle_transform.location
                        walker_loc = walker.get_transform().location

                        # Distance check (50m range)
                        dist = vehicle_loc.distance(walker_loc)
                        if dist > 50.0:
                            continue
                        # Dot product: is walker in front of vehicle?
                        dx = walker_loc.x - vehicle_loc.x
                        dy = walker_loc.y - vehicle_loc.y
                        dot = forward_vec.x * dx + forward_vec.y * dy
                        if dot > 0:
                            loc = walker_loc
                            lat, lon = carla_location_to_wgs84(loc)
                            elev = loc.z
                            history_buffer = [{
                                "lat": lat,
                                "lon": lon,
                                "elev": elev,
                                "timeOffset": int(500)
                            }]
                            
                            psm_msg = generate_psm(walker, history_buffer, reference_lat=-23.4703361, reference_lon=-47.4308804, reference_elev=0.0, msg_count=msg_cnt)
                            psm_generated = True
                            break

                # 4. Broadcast Payloads individually over TCP (C-V2X) and UDP (5G)
                try:
                    # PATH 1: C-V2X (TCP → RSU → DSRC)
                    if bsm_msgs:
                        for b in bsm_msgs:
                            sender.send_event(b, seq=msg_cnt)
                    if psm_msg: sender.send_event(psm_msg, seq=msg_cnt)
                    # if tim_msg: sender.send_event(tim_msg, seq=msg_cnt)
                    # if rsa_msg: sender.send_event(rsa_msg, seq=msg_cnt)
                    # if map_msg: sender.send_event(map_msg, seq=msg_cnt)
                    # if spat_msg: sender.send_event(spat_msg, seq=msg_cnt)

                    # PATH 2: 5G Slice (UDP → forwarder → 5G core → OBU)
                    if sender_5g:
                        if bsm_msgs:
                            for b in bsm_msgs:
                                sender_5g.send_event(b, seq=msg_cnt)
                        if psm_msg:  sender_5g.send_event(psm_msg, seq=msg_cnt)
                        if tim_msg:  sender_5g.send_event(tim_msg, seq=msg_cnt)
                        if rsa_msg:  sender_5g.send_event(rsa_msg, seq=msg_cnt)
                        if map_msg:  sender_5g.send_event(map_msg, seq=msg_cnt)
                        if spat_msg: sender_5g.send_event(spat_msg, seq=msg_cnt)
                except KeyboardInterrupt:
                    pass
                
                last_run = current_time
                msg_cnt += 1
    finally:

        if world is not None:
            world.destroy()
        if sender is not None:
            sender.close()
        if sender_5g is not None:
            sender_5g.close()

        pygame.quit()


# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def main():
    argparser = argparse.ArgumentParser(
        description='CARLA Manual Control Client')
    argparser.add_argument(
        '-v', '--verbose',
        action='store_true',
        dest='debug',
        help='print debug information')
    argparser.add_argument(
        '--host',
        metavar='H',
        default='127.0.0.1',
        help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument(
        '-p', '--port',
        metavar='P',
        default=2000,
        type=int,
        help='TCP port to listen to (default: 2000)')
    argparser.add_argument(
        '-a', '--autopilot',
        action='store_true',
        help='enable autopilot')
    argparser.add_argument(
        '-sw', '--steeringwheel',
        action='store_true',
        help='enable steeringwheel')
    argparser.add_argument(
        '-w', '--workstation',
        action='store_true',
        help='enable workstation')
    argparser.add_argument(
        '--res',
        metavar='WIDTHxHEIGHT',
        default='1920x1080',
        help='window resolution (default: 1280x720)')
    argparser.add_argument(
        '--filter',
        metavar='PATTERN',
        default='vehicle.*',
        help='actor filter (default: "vehicle.*")')
    argparser.add_argument(
        '--map-file',
        default=None,
        help='path to dynamic J2735 map payload JSON (default: map_cruzamento.json)')
    argparser.add_argument(
        '--v2x-5g-ip',
        default=None,
        help='IP of 5G RSU forwarder or OBU on V2X slice (enables dual-path 5G). '
             'Example: --v2x-5g-ip 192.168.200.2')
    argparser.add_argument(
        '--v2x-5g-port',
        type=int,
        default=9090,
        help='UDP port for 5G V2X path (default: 9090)')
    # Nota: a URL do servidor DDNS é configurada automaticamente via v2x_ddns.conf
    # Não é mais necessário passar --ddns-url na linha de comando.
    args = argparser.parse_args()

    # Uses 3 screen size on workstation
    if args.workstation == True:
        args.width, args.height = 5760, 1080
    else:
        args.width, args.height = [int(x) for x in args.res.split('x')]

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=log_level)

    logging.info('listening to server %s:%s', args.host, args.port)
    
    logi_controller = LogitechController()
    if args.steeringwheel and not LOGITECH_AVAILABLE:
        print("WARNING: logidrivepy is not available on this OS/Environment (Linux/Mac). Steering wheel support disabled, falling back to keyboard/joystick.")
        args.steeringwheel = False

    print(__doc__)
    try:
        
        threading.Thread(
            target=pure_pursuit.pure_pursuit,
            daemon=True
        ).start()
        game_loop(args, logi_controller)

    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')
        if args.steeringwheel == True: logi_controller.steering_shutdown()  # type: ignore


if __name__ == '__main__':

    main()
