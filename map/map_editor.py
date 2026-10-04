"""
地图编辑器与自定义系统 - 核心模块

功能：
- 地形编辑：高度调整、挖洞、材质
- 物体放置：武器/道具/障碍物，位置与旋转调整，复制粘贴
- 地图保存：JSON 格式持久化，带校验和验证
- 地图测试：可玩性检查、碰撞检测、出生点
- 地图分享：审核、评分
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
import copy
import hashlib
import json
import math
import os
import time


MAP_FORMAT = "gsb-map"
MAP_VERSION = 1

MATERIALS = ("grass", "dirt", "stone", "sand", "water", "lava")
OBJECT_TYPES = ("weapon", "item", "obstacle")

# 高度达到该值的格子视为墙体，玩家无法穿过
WALL_HEIGHT = 2.0
# 挖洞深度下限
MIN_HEIGHT = -8.0
MAX_HEIGHT = 16.0


class MapValidationError(Exception):
    """地图数据验证失败。"""


class MapReviewError(Exception):
    """地图审核失败。"""


@dataclass
class Config:
    pass


@dataclass
class TerrainCell:
    height: float = 0.0
    material: str = "grass"

    def to_dict(self) -> Dict:
        return {"height": self.height, "material": self.material}

    @staticmethod
    def from_dict(data: Dict) -> "TerrainCell":
        return TerrainCell(height=float(data["height"]), material=str(data["material"]))


@dataclass
class MapObject:
    object_id: int
    object_type: str
    position: Tuple[float, float, float]
    rotation: float = 0.0
    properties: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "position": list(self.position),
            "rotation": self.rotation,
            "properties": self.properties,
        }

    @staticmethod
    def from_dict(data: Dict) -> "MapObject":
        return MapObject(
            object_id=int(data["object_id"]),
            object_type=str(data["object_type"]),
            position=tuple(float(v) for v in data["position"]),
            rotation=float(data.get("rotation", 0.0)),
            properties=dict(data.get("properties", {})),
        )


class MapEditor:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.width = int(self.config.get("width", 32))
        self.height = int(self.config.get("height", 32))
        self.save_dir = self.config.get("save_dir", "maps")
        self._state = {}
        self._history = []
        self._terrain: Dict[Tuple[int, int], TerrainCell] = {}
        self._objects: Dict[int, MapObject] = {}
        self._next_object_id = 1
        self._clipboard: Optional[MapObject] = None
        self._spawn_points: List[Tuple[float, float]] = []
        self._shared_maps: Dict[int, Dict] = {}
        self._next_share_id = 1

    # ------------------------------------------------------------------
    # 框架接口
    # ------------------------------------------------------------------
    def update(self, dt: float):
        pass

    def reset(self):
        self._state = {}
        self._history = []
        self._terrain = {}
        self._objects = {}
        self._next_object_id = 1
        self._clipboard = None
        self._spawn_points = []
        self._shared_maps = {}
        self._next_share_id = 1

    # ------------------------------------------------------------------
    # 地形编辑：高度 / 挖洞 / 材质
    # ------------------------------------------------------------------
    def _check_bounds(self, x: int, y: int):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"坐标越界: ({x}, {y})")

    def _cell(self, x: int, y: int) -> TerrainCell:
        self._check_bounds(x, y)
        key = (x, y)
        if key not in self._terrain:
            self._terrain[key] = TerrainCell()
        return self._terrain[key]

    def get_height(self, x: int, y: int) -> float:
        return self._cell(x, y).height

    def set_height(self, x: int, y: int, height: float) -> float:
        cell = self._cell(x, y)
        cell.height = max(MIN_HEIGHT, min(MAX_HEIGHT, float(height)))
        return cell.height

    def raise_terrain(self, x: int, y: int, amount: float = 1.0) -> float:
        return self.set_height(x, y, self.get_height(x, y) + amount)

    def dig(self, x: int, y: int, depth: float = 1.0) -> float:
        """挖洞：降低地形高度，可挖到海平面以下。"""
        if depth <= 0:
            raise ValueError("挖掘深度必须为正数")
        return self.set_height(x, y, self.get_height(x, y) - depth)

    def set_material(self, x: int, y: int, material: str):
        if material not in MATERIALS:
            raise ValueError(f"未知材质: {material}，可选: {MATERIALS}")
        self._cell(x, y).material = material

    def get_material(self, x: int, y: int) -> str:
        return self._cell(x, y).material

    # ------------------------------------------------------------------
    # 物体放置：放置 / 调整位置旋转 / 复制粘贴
    # ------------------------------------------------------------------
    def place_object(
        self,
        object_type: str,
        position: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotation: float = 0.0,
        properties: Optional[Dict] = None,
    ) -> int:
        if object_type not in OBJECT_TYPES:
            raise ValueError(f"未知物体类型: {object_type}，可选: {OBJECT_TYPES}")
        obj = MapObject(
            object_id=self._next_object_id,
            object_type=object_type,
            position=tuple(float(v) for v in position),
            rotation=float(rotation) % 360.0,
            properties=dict(properties or {}),
        )
        self._objects[obj.object_id] = obj
        self._next_object_id += 1
        return obj.object_id

    def get_object(self, object_id: int) -> MapObject:
        if object_id not in self._objects:
            raise KeyError(f"物体不存在: {object_id}")
        return self._objects[object_id]

    def list_objects(self) -> List[MapObject]:
        return list(self._objects.values())

    def move_object(self, object_id: int, position: Tuple[float, float, float]):
        self.get_object(object_id).position = tuple(float(v) for v in position)

    def rotate_object(self, object_id: int, rotation: float):
        obj = self.get_object(object_id)
        obj.rotation = float(rotation) % 360.0

    def remove_object(self, object_id: int):
        self.get_object(object_id)
        del self._objects[object_id]

    def copy_object(self, object_id: int) -> int:
        """复制物体到剪贴板，返回剪贴板中物体的源 id。"""
        self._clipboard = copy.deepcopy(self.get_object(object_id))
        return object_id

    def paste_object(
        self, position: Optional[Tuple[float, float, float]] = None
    ) -> int:
        """粘贴剪贴板中的物体，返回新物体 id。"""
        if self._clipboard is None:
            raise ValueError("剪贴板为空，请先复制物体")
        src = self._clipboard
        return self.place_object(
            src.object_type,
            position if position is not None else src.position,
            src.rotation,
            src.properties,
        )

    # ------------------------------------------------------------------
    # 出生点
    # ------------------------------------------------------------------
    def add_spawn_point(self, x: float, y: float) -> Tuple[float, float]:
        point = (float(x), float(y))
        self._spawn_points.append(point)
        return point

    def get_spawn_points(self) -> List[Tuple[float, float]]:
        return list(self._spawn_points)

    # ------------------------------------------------------------------
    # 地图保存：JSON 格式 + 校验和验证 + 持久化
    # ------------------------------------------------------------------
    def serialize(self) -> Dict:
        payload = {
            "width": self.width,
            "height": self.height,
            "terrain": [
                {"x": x, "y": y, **cell.to_dict()}
                for (x, y), cell in sorted(self._terrain.items())
            ],
            "objects": [obj.to_dict() for obj in self._objects.values()],
            "spawn_points": [list(p) for p in self._spawn_points],
        }
        checksum = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            "format": MAP_FORMAT,
            "version": MAP_VERSION,
            "saved_at": time.time(),
            "checksum": checksum,
            "payload": payload,
        }

    def _validate(self, data: Dict) -> Dict:
        if not isinstance(data, dict):
            raise MapValidationError("地图数据必须是 JSON 对象")
        if data.get("format") != MAP_FORMAT:
            raise MapValidationError(f"未知地图格式: {data.get('format')!r}")
        if data.get("version") != MAP_VERSION:
            raise MapValidationError(f"不支持的地图版本: {data.get('version')!r}")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise MapValidationError("地图缺少 payload")
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if data.get("checksum") != expected:
            raise MapValidationError("校验和不匹配，地图文件可能已损坏")
        return payload

    def save_map(self, name: str = "map") -> str:
        """保存地图到磁盘（JSON 格式），返回文件路径。"""
        os.makedirs(self.save_dir, exist_ok=True)
        path = os.path.join(self.save_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.serialize(), fh, ensure_ascii=False, indent=2)
        return path

    def load_map(self, path: str):
        """从磁盘加载地图，加载前进行格式与校验和验证。"""
        with open(path, "r", encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise MapValidationError(f"地图文件不是合法 JSON: {exc}") from exc
        payload = self._validate(data)
        self.width = int(payload["width"])
        self.height = int(payload["height"])
        self._terrain = {}
        for entry in payload.get("terrain", []):
            key = (int(entry["x"]), int(entry["y"]))
            self._terrain[key] = TerrainCell.from_dict(entry)
        self._objects = {}
        self._next_object_id = 1
        for obj_data in payload.get("objects", []):
            obj = MapObject.from_dict(obj_data)
            self._objects[obj.object_id] = obj
            self._next_object_id = max(self._next_object_id, obj.object_id + 1)
        self._spawn_points = [tuple(p) for p in payload.get("spawn_points", [])]

    # ------------------------------------------------------------------
    # 地图测试：可玩性 / 碰撞检测 / 出生点
    # ------------------------------------------------------------------
    def is_solid(self, x: int, y: int) -> bool:
        """高度达到墙体阈值的格子不可通行。"""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return True
        return self._terrain.get((x, y), TerrainCell()).height >= WALL_HEIGHT

    def check_collision(self, x: float, y: float) -> bool:
        """检测玩家在给定位置是否会穿墙，True 表示发生碰撞。"""
        return self.is_solid(int(math.floor(x)), int(math.floor(y)))

    def move_player(
        self, x: float, y: float, dx: float, dy: float
    ) -> Tuple[float, float]:
        """尝试移动玩家，撞墙时停在原地（不允许穿墙）。"""
        nx, ny = x + dx, y + dy
        if self.check_collision(nx, ny):
            return (x, y)
        return (nx, ny)

    def test_map(self) -> Dict:
        """测试地图可玩性，返回测试报告。"""
        issues = []
        if not self._spawn_points:
            issues.append("缺少出生点，玩家不知道从哪里开始")
        reachable = 0
        total_open = 0
        if self._spawn_points:
            reachable, total_open = self._flood_fill_reachable()
            if total_open > 0 and reachable == 0:
                issues.append("出生点被墙体包围，玩家无法移动")
            elif reachable < total_open:
                issues.append("部分区域被墙体封锁，玩家无法到达")
        spawn = self._spawn_points[0] if self._spawn_points else None
        collision_ok = True
        if spawn is not None:
            # 出生点本身不能在墙里
            if self.check_collision(spawn[0], spawn[1]):
                collision_ok = False
                issues.append("出生点位于墙体内部")
        playable = not issues
        return {
            "playable": playable,
            "spawn_points": len(self._spawn_points),
            "collision_ok": collision_ok,
            "reachable_tiles": reachable,
            "open_tiles": total_open,
            "issues": issues,
        }

    def _flood_fill_reachable(self) -> Tuple[int, int]:
        start = self._spawn_points[0]
        sx, sy = int(math.floor(start[0])), int(math.floor(start[1]))
        open_tiles = {
            (x, y)
            for x in range(self.width)
            for y in range(self.height)
            if not self.is_solid(x, y)
        }
        if (sx, sy) not in open_tiles:
            return 0, len(open_tiles)
        seen = {(sx, sy)}
        stack = [(sx, sy)]
        while stack:
            cx, cy = stack.pop()
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in open_tiles and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        return len(seen), len(open_tiles)

    # ------------------------------------------------------------------
    # 地图分享：分享 / 审核 / 评分
    # ------------------------------------------------------------------
    def share_map(self, author: str, name: str = "map") -> int:
        """分享地图，进入待审核队列，返回分享 id。"""
        if not author:
            raise ValueError("作者不能为空")
        report = self.test_map()
        share_id = self._next_share_id
        self._next_share_id += 1
        self._shared_maps[share_id] = {
            "share_id": share_id,
            "author": author,
            "name": name,
            "data": self.serialize(),
            "status": "pending",
            "reviewer": None,
            "auto_checks": {
                "playable": report["playable"],
                "has_spawn": report["spawn_points"] > 0,
                "collision_ok": report["collision_ok"],
            },
            "ratings": {},
            "shared_at": time.time(),
        }
        return share_id

    def get_shared_map(self, share_id: int) -> Dict:
        if share_id not in self._shared_maps:
            raise KeyError(f"分享不存在: {share_id}")
        return self._shared_maps[share_id]

    def review_map(self, share_id: int, approved: bool, reviewer: str = "admin"):
        """审核地图：自动检查不通过的地图（作弊/不可玩）不能审核通过。"""
        entry = self.get_shared_map(share_id)
        if entry["status"] != "pending":
            raise MapReviewError(f"地图已被审核，当前状态: {entry['status']}")
        checks = entry["auto_checks"]
        if approved and not all(checks.values()):
            entry["status"] = "rejected"
            entry["reviewer"] = reviewer
            raise MapReviewError(f"自动检查未通过，无法审核通过: {checks}")
        entry["status"] = "approved" if approved else "rejected"
        entry["reviewer"] = reviewer
        return entry["status"]

    def rate_map(self, share_id: int, user: str, score: float):
        """为已审核通过的地图评分（1-5 分）。"""
        entry = self.get_shared_map(share_id)
        if entry["status"] != "approved":
            raise MapReviewError("只有审核通过的地图才能评分")
        if not user:
            raise ValueError("评分用户不能为空")
        if not (1.0 <= float(score) <= 5.0):
            raise ValueError("评分必须在 1-5 之间")
        entry["ratings"][user] = float(score)

    def get_rating(self, share_id: int) -> Optional[float]:
        """返回地图平均评分，暂无评分时返回 None。"""
        ratings = self.get_shared_map(share_id)["ratings"]
        if not ratings:
            return None
        return sum(ratings.values()) / len(ratings)

    def list_shared_maps(self, status: str = "approved") -> List[Dict]:
        return [
            {
                "share_id": e["share_id"],
                "author": e["author"],
                "name": e["name"],
                "status": e["status"],
                "rating": self.get_rating(e["share_id"]),
            }
            for e in self._shared_maps.values()
            if e["status"] == status
        ]
