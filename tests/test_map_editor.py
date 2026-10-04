"""
地图编辑器与自定义系统 - 验收测试
运行方式：python -m pytest tests/test_map_editor.py -q
共 14 个测试用例
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map.map_editor import MapEditor, MapValidationError, MapReviewError


class TestMapEditor:
    def setup_method(self):
        self.system = MapEditor({"width": 16, "height": 16})

    # ---- 地形编辑 ----
    def test_case_01(self):
        """地形编辑支持调整高度"""
        e = self.system
        assert e.get_height(3, 4) == 0.0
        e.set_height(3, 4, 5.0)
        assert e.get_height(3, 4) == 5.0
        e.raise_terrain(3, 4, 2.0)
        assert e.get_height(3, 4) == 7.0
        with pytest.raises(ValueError):
            e.set_height(99, 99, 1.0)

    def test_case_02(self):
        """地形编辑支持挖洞（高度可降到海平面以下）"""
        e = self.system
        e.dig(5, 5, 3.0)
        assert e.get_height(5, 5) == -3.0
        e.dig(5, 5, 2.0)
        assert e.get_height(5, 5) == -5.0
        with pytest.raises(ValueError):
            e.dig(5, 5, -1.0)

    def test_case_03(self):
        """地形支持材质，不同方块可有不同材质"""
        e = self.system
        assert e.get_material(0, 0) == "grass"
        e.set_material(0, 0, "stone")
        e.set_material(1, 0, "water")
        assert e.get_material(0, 0) == "stone"
        assert e.get_material(1, 0) == "water"
        with pytest.raises(ValueError):
            e.set_material(0, 0, "unobtainium")

    # ---- 物体放置 ----
    def test_case_04(self):
        """物体放置支持武器、道具、障碍物"""
        e = self.system
        wid = e.place_object("weapon", (1, 2, 0), properties={"name": "sword"})
        iid = e.place_object("item", (3, 4, 0))
        oid = e.place_object("obstacle", (5, 6, 0))
        assert len(e.list_objects()) == 3
        assert e.get_object(wid).object_type == "weapon"
        assert e.get_object(iid).object_type == "item"
        assert e.get_object(oid).object_type == "obstacle"
        with pytest.raises(ValueError):
            e.place_object("nuke", (0, 0, 0))

    def test_case_05(self):
        """物体可调整位置和旋转"""
        e = self.system
        oid = e.place_object("obstacle", (0, 0, 0))
        e.move_object(oid, (10, 11, 2))
        assert e.get_object(oid).position == (10.0, 11.0, 2.0)
        e.rotate_object(oid, 90)
        assert e.get_object(oid).rotation == 90.0
        e.rotate_object(oid, 450)
        assert e.get_object(oid).rotation == 90.0

    def test_case_06(self):
        """物体支持复制粘贴，无需每个重新放置"""
        e = self.system
        oid = e.place_object("weapon", (1, 1, 0), rotation=45,
                             properties={"name": "axe"})
        e.copy_object(oid)
        new1 = e.paste_object((5, 5, 0))
        new2 = e.paste_object((6, 6, 0))
        assert new1 != oid and new2 != oid and new1 != new2
        obj = e.get_object(new1)
        assert obj.object_type == "weapon"
        assert obj.position == (5.0, 5.0, 0.0)
        assert obj.rotation == 45.0
        assert obj.properties["name"] == "axe"
        assert len(e.list_objects()) == 3

    # ---- 地图保存 ----
    def test_case_07(self, tmp_path=None):
        """地图保存持久化到磁盘，且为 JSON 格式"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            e = MapEditor({"save_dir": d})
            e.set_height(1, 1, 3.0)
            e.set_material(1, 1, "stone")
            path = e.save_map("level1")
            assert os.path.exists(path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)  # 必须是合法 JSON，不是裸二进制
            assert data["format"] == "gsb-map"
            assert data["version"] == 1
            assert data["checksum"]

    def test_case_08(self):
        """保存的地图可完整加载（往返一致）"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            e = MapEditor({"save_dir": d, "width": 8, "height": 8})
            e.set_height(2, 2, 4.0)
            e.set_material(3, 3, "sand")
            e.place_object("item", (1, 1, 0), rotation=30)
            e.add_spawn_point(0, 0)
            path = e.save_map("roundtrip")
            e2 = MapEditor({"save_dir": d})
            e2.load_map(path)
            assert e2.get_height(2, 2) == 4.0
            assert e2.get_material(3, 3) == "sand"
            assert len(e2.list_objects()) == 1
            assert e2.list_objects()[0].rotation == 30.0
            assert e2.get_spawn_points() == [(0.0, 0.0)]

    def test_case_09(self):
        """保存带验证：损坏的地图文件会被拒绝"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            e = MapEditor({"save_dir": d})
            path = e.save_map("broken")
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data["payload"]["height"] = 999  # 篡改内容，校验和不再匹配
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            with pytest.raises(MapValidationError):
                e.load_map(path)
            bad = os.path.join(d, "garbage.json")
            with open(bad, "wb") as fh:
                fh.write(b"\x00\x01\x02 not json")
            with pytest.raises(MapValidationError):
                e.load_map(bad)

    # ---- 地图测试 ----
    def test_case_10(self):
        """地图测试报告可玩性，并要求有出生点"""
        e = self.system
        report = e.test_map()
        assert report["playable"] is False
        assert any("出生点" in issue for issue in report["issues"])
        e.add_spawn_point(1, 1)
        report = e.test_map()
        assert report["playable"] is True
        assert report["spawn_points"] == 1
        assert report["issues"] == []

    def test_case_11(self):
        """测试带碰撞检测，玩家不能穿墙"""
        e = self.system
        e.set_height(4, 4, 3.0)  # 墙
        assert e.check_collision(4, 4) is True
        assert e.check_collision(0, 0) is False
        # 玩家从 (3,4) 向墙移动会被挡住
        assert e.move_player(3.0, 4.0, 1.0, 0.0) == (3.0, 4.0)
        # 向空地移动正常
        assert e.move_player(3.0, 4.0, -1.0, 0.0) == (2.0, 4.0)

    def test_case_12(self):
        """被墙围死的出生点会被测试判定为不可玩"""
        e = MapEditor({"width": 5, "height": 5})
        e.add_spawn_point(2, 2)
        for x, y in ((1, 2), (3, 2), (2, 1), (2, 3)):
            e.set_height(x, y, 3.0)
        report = e.test_map()
        assert report["playable"] is False
        assert report["reachable_tiles"] == 1
        assert report["open_tiles"] > 1

    # ---- 地图分享 ----
    def test_case_13(self):
        """地图分享需审核，作弊/不可玩地图无法通过审核"""
        e = self.system
        e.add_spawn_point(1, 1)
        sid = e.share_map(author="alice", name="good-map")
        assert e.get_shared_map(sid)["status"] == "pending"
        assert e.review_map(sid, approved=True) == "approved"
        assert e.list_shared_maps()[0]["share_id"] == sid
        # 不可玩地图（无出生点）审核通过时应被拒绝
        e2 = self.system.__class__({"width": 8, "height": 8})
        bad_id = e2.share_map(author="cheater", name="cheat-map")
        with pytest.raises(MapReviewError):
            e2.review_map(bad_id, approved=True)
        assert e2.get_shared_map(bad_id)["status"] == "rejected"

    def test_case_14(self):
        """分享地图支持评分，玩家可看到地图好坏"""
        e = self.system
        e.add_spawn_point(1, 1)
        sid = e.share_map(author="bob", name="fun-map")
        # 未审核通过不能评分
        with pytest.raises(MapReviewError):
            e.rate_map(sid, "u1", 5)
        e.review_map(sid, approved=True)
        assert e.get_rating(sid) is None
        e.rate_map(sid, "u1", 5)
        e.rate_map(sid, "u2", 3)
        assert e.get_rating(sid) == 4.0
        with pytest.raises(ValueError):
            e.rate_map(sid, "u3", 99)
        listed = e.list_shared_maps()
        assert listed[0]["rating"] == 4.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
