"""
地图编辑器与自定义系统 - 验收测试
运行方式：python -m pytest tests/test_map_editor.py -q
共 14 个测试用例
"""
import json

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map.map_editor import MapEditor


class TestMapEditor:
    def setup_method(self):
        self.system = MapEditor()

    # ---- 地形编辑 ----

    def test_case_01(self):
        """地形编辑支持调整高度"""
        assert self.system.get_height(3, 4) == 0
        self.system.set_height(3, 4, 5)
        assert self.system.get_height(3, 4) == 5
        self.system.raise_terrain(3, 4, 2)
        assert self.system.get_height(3, 4) == 7
        self.system.lower_terrain(3, 4, 3)
        assert self.system.get_height(3, 4) == 4
        with pytest.raises(ValueError):
            self.system.set_height(0, 0, 9999)

    def test_case_02(self):
        """地形编辑支持挖洞（高度可低于地面）"""
        self.system.dig_hole(1, 1, 3)
        assert self.system.get_height(1, 1) == -3
        self.system.dig_hole(1, 1, 2)
        assert self.system.get_height(1, 1) == -5
        with pytest.raises(ValueError):
            self.system.dig_hole(1, 1, 0)

    def test_case_03(self):
        """地形方块支持不同材质"""
        self.system.place_block(0, 0, material="stone")
        assert self.system.get_material(0, 0) == "stone"
        self.system.set_material(0, 0, "sand")
        assert self.system.get_material(0, 0) == "sand"
        assert self.system.get_material(5, 5) == "grass"  # 默认材质
        with pytest.raises(ValueError):
            self.system.set_material(0, 0, "unobtainium")

    # ---- 物体放置 ----

    def test_case_04(self):
        """可以放置武器、道具、障碍物"""
        weapon = self.system.place_object("weapon", (1, 0, 1), name="rifle")
        item = self.system.place_object("item", (2, 0, 2), name="medkit")
        obstacle = self.system.place_object("obstacle", (3, 0, 3))
        assert len(self.system.list_objects()) == 3
        assert self.system.get_object(weapon)["properties"]["name"] == "rifle"
        assert self.system.get_object(item)["type"] == "item"
        assert self.system.get_object(obstacle)["type"] == "obstacle"
        with pytest.raises(ValueError):
            self.system.place_object("nonsense", (0, 0, 0))

    def test_case_05(self):
        """物体可以调整位置和旋转"""
        obj_id = self.system.place_object("prop", (0, 0, 0))
        self.system.move_object(obj_id, (5, 1, 7))
        assert self.system.get_object(obj_id)["position"] == (5, 1, 7)
        self.system.rotate_object(obj_id, 90)
        assert self.system.get_object(obj_id)["rotation"] == 90
        self.system.rotate_object(obj_id, 450)
        assert self.system.get_object(obj_id)["rotation"] == 90  # 归一化到 360 内
        with pytest.raises(KeyError):
            self.system.move_object(9999, (0, 0, 0))

    def test_case_06(self):
        """物体可以复制粘贴"""
        src = self.system.place_object("weapon", (1, 0, 1), rotation=45, name="ak")
        clone = self.system.copy_object(src, position=(9, 0, 9))
        assert clone != src
        src_obj = self.system.get_object(src)
        clone_obj = self.system.get_object(clone)
        assert clone_obj["type"] == src_obj["type"] == "weapon"
        assert clone_obj["rotation"] == src_obj["rotation"] == 45
        assert clone_obj["properties"] == src_obj["properties"]
        assert clone_obj["position"] == (9, 0, 9)
        assert len(self.system.list_objects()) == 2

    # ---- 地图保存 ----

    def test_case_07(self):
        """地图保存后可持久化并完整恢复"""
        self.system.set_height(2, 2, 4)
        self.system.set_material(2, 2, "metal")
        self.system.place_object("item", (1, 0, 1), name="ammo")
        self.system.set_spawn_point((0, 0, 0))
        data = self.system.save_map()

        restored = MapEditor()
        restored.load_map(data)
        assert restored.get_height(2, 2) == 4
        assert restored.get_material(2, 2) == "metal"
        assert restored.get_object(1)["properties"]["name"] == "ammo"
        assert restored.get_spawn_point() == (0.0, 0.0, 0.0)

    def test_case_08(self):
        """保存使用带版本与校验和的 JSON 格式"""
        self.system.place_block(0, 0)
        document = json.loads(self.system.save_map())
        assert document["magic"] == "PMAP"
        assert document["version"] == 1
        assert isinstance(document["checksum"], str) and len(document["checksum"]) == 64
        assert "terrain" in document["payload"]
        assert "objects" in document["payload"]

    def test_case_09(self):
        """损坏或篡改的地图数据会被验证拒绝"""
        self.system.place_block(0, 0)
        document = json.loads(self.system.save_map())
        document["payload"]["terrain"][0]["height"] = 99  # 篡改数据
        with pytest.raises(ValueError):
            self.system.load_map(json.dumps(document))
        with pytest.raises(ValueError):
            self.system.load_map("这不是JSON")
        with pytest.raises(ValueError):
            self.system.load_map(json.dumps({"magic": "FAKE"}))

    # ---- 地图测试 ----

    def test_case_10(self):
        """地图测试报告可玩性问题"""
        report = self.system.test_map()
        assert report["playable"] is False
        assert any("出生点" in issue for issue in report["issues"])

        self.system.set_spawn_point((0, 0, 0))
        self.system.place_object("weapon", (1, 0, 1))
        report = self.system.test_map()
        assert report["playable"] is True
        assert report["issues"] == []

    def test_case_11(self):
        """测试模式有碰撞检测，玩家不能穿墙"""
        self.system.set_spawn_point((0, 0, 0))
        self.system.spawn_player()
        self.system.set_height(1, 0, 2)  # 造一堵墙
        assert self.system.check_collision(1, 0) is True
        assert self.system.move_player(1, 0) is False  # 撞墙，原地不动
        assert self.system.get_player_position() == (0.0, 0.0, 0.0)
        assert self.system.move_player(0, 1) is True  # 平地可走
        assert self.system.get_player_position() == (0.0, 0.0, 1.0)

    def test_case_12(self):
        """地图测试有出生点，玩家从出生点开始"""
        assert self.system.get_spawn_point() is None
        with pytest.raises(ValueError):
            self.system.spawn_player()
        self.system.set_spawn_point((3, 0, 4))
        assert self.system.get_spawn_point() == (3.0, 0.0, 4.0)
        assert self.system.spawn_player() == (3.0, 0.0, 4.0)
        self.system.set_height(8, 8, 3)
        with pytest.raises(ValueError):
            self.system.set_spawn_point((8, 0, 8))  # 出生点不能在墙里

    # ---- 地图分享 ----

    def test_case_13(self):
        """地图分享需要审核，作弊/不可玩地图不能上架"""
        # 不可玩地图（无出生点）被自动拒绝
        bad_id = self.system.share_map(author="cheater", name="作弊图")
        assert self.system.get_shared_map(bad_id)["status"] == "rejected"

        # 正常地图进入待审核，审核通过后才可见
        self.system.set_spawn_point((0, 0, 0))
        self.system.place_object("item", (1, 0, 1))
        good_id = self.system.share_map(author="maker", name="好图")
        assert self.system.get_shared_map(good_id)["status"] == "pending"
        assert self.system.list_shared_maps() == []
        self.system.review_shared_map(good_id, approved=True)
        assert self.system.get_shared_map(good_id)["status"] == "approved"
        assert [m["id"] for m in self.system.list_shared_maps()] == [good_id]

    def test_case_14(self):
        """已审核地图可以评分并计算平均分"""
        self.system.set_spawn_point((0, 0, 0))
        self.system.place_object("weapon", (1, 0, 1))
        share_id = self.system.share_map(author="maker")

        with pytest.raises(ValueError):
            self.system.rate_shared_map(share_id, "alice", 5)  # 未审核不能评分
        self.system.review_shared_map(share_id, approved=True)

        assert self.system.get_shared_map_rating(share_id) is None
        assert self.system.rate_shared_map(share_id, "alice", 5) == 5.0
        assert self.system.rate_shared_map(share_id, "bob", 3) == 4.0
        assert self.system.get_shared_map(share_id)["rating"] == 4.0
        with pytest.raises(ValueError):
            self.system.rate_shared_map(share_id, "carol", 6)  # 超出 1-5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
