"""
地图编辑器与自定义系统 - 核心模块

功能：
- 地形编辑：放置方块、调整高度、挖洞、设置材质
- 物体放置：放置武器/道具/障碍物，移动、旋转、复制粘贴
- 地图保存：JSON 格式持久化，带版本与校验和验证
- 地图测试：可玩性检查、碰撞检测、出生点
- 地图分享：分享、审核、评分
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import copy
import hashlib
import json
import math
import time

MAP_MAGIC = "PMAP"
MAP_FORMAT_VERSION = 1

DEFAULT_MATERIAL = "grass"
MATERIALS = {"grass", "stone", "sand", "dirt", "snow", "metal", "wood", "water"}
MIN_HEIGHT = -16
MAX_HEIGHT = 64
# 高度达到该值的格子视为墙体，会阻挡玩家移动
WALL_HEIGHT = 1

OBJECT_TYPES = {"weapon", "item", "obstacle", "prop", "decoration"}


@dataclass
class Config:
    pass


class MapEditor:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._state = {}
        self._history = []
        # 地形: (x, z) -> {"height": int, "material": str}
        self._terrain: Dict[Tuple[int, int], Dict] = {}
        # 物体: id -> {"id", "type", "position", "rotation", "properties"}
        self._objects: Dict[int, Dict] = {}
        self._next_object_id = 1
        self._spawn_point: Optional[Tuple[float, float, float]] = None
        self._player_position: Optional[Tuple[float, float, float]] = None
        # 分享: id -> {"id", "author", "name", "data", "status", "ratings"}
        self._shared_maps: Dict[int, Dict] = {}
        self._next_share_id = 1

    def update(self, dt: float):
        pass

    def reset(self):
        self._state = {}
        self._history = []
        self._terrain = {}
        self._objects = {}
        self._next_object_id = 1
        self._spawn_point = None
        self._player_position = None
        self._shared_maps = {}
        self._next_share_id = 1

    # ------------------------------------------------------------------
    # 地形编辑
    # ------------------------------------------------------------------
    def _cell(self, x: int, z: int) -> Dict:
        key = (int(x), int(z))
        if key not in self._terrain:
            self._terrain[key] = {"height": 0, "material": DEFAULT_MATERIAL}
        return self._terrain[key]

    def place_block(self, x: int, z: int, material: str = DEFAULT_MATERIAL) -> Dict:
        cell = self._cell(x, z)
        cell["height"] = max(cell["height"], WALL_HEIGHT)
        self.set_material(x, z, material)
        return dict(cell)

    def get_height(self, x: int, z: int) -> int:
        return self._cell(x, z)["height"]

    def set_height(self, x: int, z: int, height: int) -> int:
        if not MIN_HEIGHT <= height <= MAX_HEIGHT:
            raise ValueError(f"高度 {height} 超出范围 [{MIN_HEIGHT}, {MAX_HEIGHT}]")
        cell = self._cell(x, z)
        cell["height"] = int(height)
        return cell["height"]

    def raise_terrain(self, x: int, z: int, amount: int = 1) -> int:
        return self.set_height(x, z, self.get_height(x, z) + amount)

    def lower_terrain(self, x: int, z: int, amount: int = 1) -> int:
        return self.set_height(x, z, self.get_height(x, z) - amount)

    def dig_hole(self, x: int, z: int, depth: int = 1) -> int:
        if depth <= 0:
            raise ValueError("挖洞深度必须为正数")
        return self.lower_terrain(x, z, depth)

    def set_material(self, x: int, z: int, material: str) -> str:
        if material not in MATERIALS:
            raise ValueError(f"未知材质: {material}")
        cell = self._cell(x, z)
        cell["material"] = material
        return cell["material"]

    def get_material(self, x: int, z: int) -> str:
        return self._cell(x, z)["material"]

    # ------------------------------------------------------------------
    # 物体放置
    # ------------------------------------------------------------------
    def place_object(self, obj_type: str, position: Tuple[float, float, float],
                     rotation: float = 0.0, **properties) -> int:
        if obj_type not in OBJECT_TYPES:
            raise ValueError(f"未知物体类型: {obj_type}")
        obj_id = self._next_object_id
        self._next_object_id += 1
        self._objects[obj_id] = {
            "id": obj_id,
            "type": obj_type,
            "position": tuple(position),
            "rotation": float(rotation) % 360.0,
            "properties": dict(properties),
        }
        return obj_id

    def get_object(self, obj_id: int) -> Dict:
        if obj_id not in self._objects:
            raise KeyError(f"物体不存在: {obj_id}")
        return copy.deepcopy(self._objects[obj_id])

    def list_objects(self) -> List[Dict]:
        return [copy.deepcopy(o) for o in self._objects.values()]

    def move_object(self, obj_id: int, position: Tuple[float, float, float]) -> Dict:
        if obj_id not in self._objects:
            raise KeyError(f"物体不存在: {obj_id}")
        self._objects[obj_id]["position"] = tuple(position)
        return self.get_object(obj_id)

    def rotate_object(self, obj_id: int, rotation: float) -> Dict:
        if obj_id not in self._objects:
            raise KeyError(f"物体不存在: {obj_id}")
        self._objects[obj_id]["rotation"] = float(rotation) % 360.0
        return self.get_object(obj_id)

    def copy_object(self, obj_id: int,
                    position: Optional[Tuple[float, float, float]] = None) -> int:
        """复制粘贴物体，返回新物体 id。"""
        if obj_id not in self._objects:
            raise KeyError(f"物体不存在: {obj_id}")
        src = self._objects[obj_id]
        return self.place_object(
            src["type"],
            position if position is not None else src["position"],
            rotation=src["rotation"],
            **copy.deepcopy(src["properties"]),
        )

    def remove_object(self, obj_id: int) -> None:
        if obj_id not in self._objects:
            raise KeyError(f"物体不存在: {obj_id}")
        del self._objects[obj_id]

    # ------------------------------------------------------------------
    # 地图保存（JSON 格式 + 校验和验证）
    # ------------------------------------------------------------------
    def _serialize_payload(self) -> Dict:
        return {
            "terrain": [
                {"x": x, "z": z, "height": c["height"], "material": c["material"]}
                for (x, z), c in sorted(self._terrain.items())
            ],
            "objects": [
                {
                    "id": o["id"],
                    "type": o["type"],
                    "position": list(o["position"]),
                    "rotation": o["rotation"],
                    "properties": o["properties"],
                }
                for o in sorted(self._objects.values(), key=lambda o: o["id"])
            ],
            "next_object_id": self._next_object_id,
            "spawn_point": list(self._spawn_point) if self._spawn_point else None,
        }

    @staticmethod
    def _checksum(payload: Dict) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def save_map(self, path: Optional[str] = None) -> str:
        """保存地图为 JSON 字符串；给定路径时同时写入文件持久化。"""
        payload = self._serialize_payload()
        document = {
            "magic": MAP_MAGIC,
            "version": MAP_FORMAT_VERSION,
            "saved_at": time.time(),
            "payload": payload,
            "checksum": self._checksum(payload),
        }
        text = json.dumps(document, ensure_ascii=False)
        if path is not None:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return text

    def load_map(self, data) -> None:
        """从 JSON 字符串/字典加载地图，带格式与校验和验证。"""
        if isinstance(data, str):
            try:
                document = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ValueError(f"地图数据不是合法 JSON: {exc}")
        elif isinstance(data, dict):
            document = data
        else:
            raise ValueError("地图数据必须是 JSON 字符串或字典")

        if not isinstance(document, dict) or document.get("magic") != MAP_MAGIC:
            raise ValueError("地图格式无效：缺少 magic 标识")
        if document.get("version") != MAP_FORMAT_VERSION:
            raise ValueError(f"不支持的地图版本: {document.get('version')}")
        payload = document.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("地图格式无效：缺少 payload")
        if document.get("checksum") != self._checksum(payload):
            raise ValueError("地图校验失败：数据已损坏")

        terrain = {}
        for cell in payload.get("terrain", []):
            key = (int(cell["x"]), int(cell["z"]))
            height = int(cell["height"])
            material = cell["material"]
            if not MIN_HEIGHT <= height <= MAX_HEIGHT:
                raise ValueError(f"地图数据损坏：高度 {height} 超出范围")
            if material not in MATERIALS:
                raise ValueError(f"地图数据损坏：未知材质 {material}")
            terrain[key] = {"height": height, "material": material}

        objects = {}
        max_id = 0
        for obj in payload.get("objects", []):
            if obj["type"] not in OBJECT_TYPES:
                raise ValueError(f"地图数据损坏：未知物体类型 {obj['type']}")
            obj_id = int(obj["id"])
            objects[obj_id] = {
                "id": obj_id,
                "type": obj["type"],
                "position": tuple(obj["position"]),
                "rotation": float(obj["rotation"]) % 360.0,
                "properties": dict(obj.get("properties", {})),
            }
            max_id = max(max_id, obj_id)

        spawn = payload.get("spawn_point")
        self._terrain = terrain
        self._objects = objects
        self._next_object_id = max(int(payload.get("next_object_id", 1)), max_id + 1)
        self._spawn_point = tuple(spawn) if spawn else None
        self._player_position = None

    # ------------------------------------------------------------------
    # 地图测试（碰撞检测 + 出生点）
    # ------------------------------------------------------------------
    def set_spawn_point(self, position: Tuple[float, float, float]) -> Tuple:
        x, y, z = position
        if self._is_solid(int(x), int(z)):
            raise ValueError("出生点不能设置在墙体内部")
        self._spawn_point = (float(x), float(y), float(z))
        return self._spawn_point

    def get_spawn_point(self) -> Optional[Tuple[float, float, float]]:
        return self._spawn_point

    def _is_solid(self, x: int, z: int) -> bool:
        return self._cell(x, z)["height"] >= WALL_HEIGHT

    def check_collision(self, x: float, z: float) -> bool:
        """目标格子为墙体（被阻挡）时返回 True。"""
        return self._is_solid(int(math.floor(x)), int(math.floor(z)))

    def spawn_player(self) -> Tuple[float, float, float]:
        if self._spawn_point is None:
            raise ValueError("地图没有设置出生点，无法开始测试")
        self._player_position = self._spawn_point
        return self._player_position

    def move_player(self, x: float, z: float) -> bool:
        """移动玩家；撞墙时保持原位并返回 False。"""
        if self._player_position is None:
            raise ValueError("玩家尚未出生，请先调用 spawn_player()")
        if self.check_collision(x, z):
            return False
        y = self._player_position[1]
        self._player_position = (float(x), y, float(z))
        return True

    def get_player_position(self) -> Optional[Tuple[float, float, float]]:
        return self._player_position

    def test_map(self) -> Dict:
        """运行可玩性测试，返回测试报告。"""
        issues = []
        if self._spawn_point is None:
            issues.append("缺少出生点")
        elif self.check_collision(self._spawn_point[0], self._spawn_point[2]):
            issues.append("出生点位于墙体内部")
        if not any(o["type"] in ("weapon", "item") for o in self._objects.values()):
            issues.append("地图没有任何武器或道具")
        return {
            "playable": not issues,
            "issues": issues,
            "spawn_point": self._spawn_point,
            "object_count": len(self._objects),
            "terrain_cells": len(self._terrain),
        }

    # ------------------------------------------------------------------
    # 地图分享（审核 + 评分）
    # ------------------------------------------------------------------
    def share_map(self, author: str, name: str = "未命名地图") -> int:
        """分享当前地图，进入待审核状态；明显不可玩的地图被自动拒绝。"""
        if not author:
            raise ValueError("作者不能为空")
        report = self.test_map()
        share_id = self._next_share_id
        self._next_share_id += 1
        status = "pending" if report["playable"] else "rejected"
        self._shared_maps[share_id] = {
            "id": share_id,
            "author": author,
            "name": name,
            "data": self.save_map(),
            "status": status,
            "review_reason": None if report["playable"] else "; ".join(report["issues"]),
            "ratings": {},
        }
        return share_id

    def review_shared_map(self, share_id: int, approved: bool, reason: str = "") -> str:
        if share_id not in self._shared_maps:
            raise KeyError(f"分享不存在: {share_id}")
        entry = self._shared_maps[share_id]
        if entry["status"] == "rejected" and entry["review_reason"] and not approved:
            raise ValueError("该地图已被自动拒绝，无需重复审核")
        entry["status"] = "approved" if approved else "rejected"
        entry["review_reason"] = reason or None
        return entry["status"]

    def rate_shared_map(self, share_id: int, user: str, score: float) -> float:
        """为已审核通过的地图评分（1-5 分），返回当前平均分。"""
        if share_id not in self._shared_maps:
            raise KeyError(f"分享不存在: {share_id}")
        entry = self._shared_maps[share_id]
        if entry["status"] != "approved":
            raise ValueError("只有审核通过的地图才能评分")
        if not 1 <= score <= 5:
            raise ValueError("评分必须在 1 到 5 之间")
        if not user:
            raise ValueError("评分用户不能为空")
        entry["ratings"][user] = float(score)
        return self.get_shared_map_rating(share_id)

    def get_shared_map_rating(self, share_id: int) -> Optional[float]:
        if share_id not in self._shared_maps:
            raise KeyError(f"分享不存在: {share_id}")
        ratings = self._shared_maps[share_id]["ratings"]
        if not ratings:
            return None
        return sum(ratings.values()) / len(ratings)

    def get_shared_map(self, share_id: int) -> Dict:
        if share_id not in self._shared_maps:
            raise KeyError(f"分享不存在: {share_id}")
        entry = dict(self._shared_maps[share_id])
        entry["ratings"] = dict(entry["ratings"])
        entry["rating"] = self.get_shared_map_rating(share_id)
        return entry

    def list_shared_maps(self, only_approved: bool = True) -> List[Dict]:
        result = []
        for share_id in sorted(self._shared_maps):
            entry = self.get_shared_map(share_id)
            if only_approved and entry["status"] != "approved":
                continue
            result.append(entry)
        return result
