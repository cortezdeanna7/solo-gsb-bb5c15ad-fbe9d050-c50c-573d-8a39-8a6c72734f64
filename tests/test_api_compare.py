"""POST /designs/{id}/compare 的接口集成测试。

使用临时 SQLite 文件与 FastAPI TestClient，不依赖运行中的服务，也不触碰
仓库默认的 data/weave.db。直接执行：python3 tests/test_api_compare.py
（也可被 pytest 收集）。
"""

import os
import sys
import tempfile

_TMP_DB = tempfile.NamedTemporaryFile(prefix="weave-test-", suffix=".db", delete=False)
_TMP_DB.close()
os.environ["DATABASE_PATH"] = _TMP_DB.name

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def shifted(matrix, dr, dc):
    """按接口约定循环平移：aligned[h][w] = matrix[(h-dr)%picks][(w-dc)%ends]。"""
    picks, ends = len(matrix), len(matrix[0])
    return [
        [matrix[(h - dr) % picks][(w - dc) % ends] for w in range(ends)]
        for h in range(picks)
    ]


def test_compare_endpoint():
    with TestClient(app) as client:
        # 基准设计 A：3 纬 × 4 经，1 在 (0,0) (1,1) (2,2)
        design_a = {
            "name": "A",
            "max_float": 4,
            "threading": [0, 1, 2, 3],
            "tie_up": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            "treadling": [0, 1, 2],
        }
        aid = client.post("/designs", json=design_a).json()["id"]
        matrix_a = client.get(f"/designs/{aid}").json()["audit"]["interlacing"]
        check(matrix_a == [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
              "design A interlacing")

        # 任一设计不存在 -> 404
        resp = client.post("/designs/99999/compare", json={"other_design_id": aid})
        check(resp.status_code == 404, "missing path design returns 404")
        check(resp.json()["detail"] == "design 99999 not found",
              "404 detail for missing path design")
        resp = client.post(f"/designs/{aid}/compare",
                           json={"other_design_id": 99999})
        check(resp.status_code == 404, "missing other design returns 404")
        check(resp.json()["detail"] == "design 99999 not found",
              "404 detail for missing other design")

        # 自身比对：零偏移、零错位
        resp = client.post(f"/designs/{aid}/compare",
                           json={"other_design_id": aid})
        check(resp.status_code == 200, "self compare returns 200")
        data = resp.json()
        check(data["design_id"] == aid and data["other_design_id"] == aid,
              "both design ids echoed")
        check(data["warp_ends"] == 4 and data["weft_picks"] == 3,
              "dimensions reported")
        check(data["row_offset"] == 0 and data["col_offset"] == 0,
              "self compare: zero offset")
        check(data["mismatches"] == 0 and data["mismatch_ratio"] == 0.0,
              "self compare: no mismatches")
        check(data["mismatch_cells"] == [], "self compare: no mismatch cells")
        check(data["row_mismatches"] == [0, 0, 0]
              and data["col_mismatches"] == [0, 0, 0, 0],
              "self compare: zero row/col summaries")
        check(data["aligned_interlacing"] == matrix_a,
              "self compare: aligned matrix equals the original")

        # B = A 向下循环 1 行、向右循环 2 列：唯一零错位对齐为偏移 (2, 2)
        design_b = {
            "name": "B",
            "max_float": 4,
            "threading": [0, 1, 2, 3],
            "tie_up": [[1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "treadling": [0, 1, 2],
        }
        bid = client.post("/designs", json=design_b).json()["id"]
        matrix_b = client.get(f"/designs/{bid}").json()["audit"]["interlacing"]
        check(matrix_b == shifted(matrix_a, 1, 2),
              "design B is A shifted by (1, 2)")
        resp = client.post(f"/designs/{aid}/compare",
                           json={"other_design_id": bid})
        check(resp.status_code == 200, "shifted compare returns 200")
        data = resp.json()
        check(data["row_offset"] == 2 and data["col_offset"] == 2,
              "unique best offset (2, 2)")
        check(data["mismatches"] == 0 and data["mismatch_ratio"] == 0.0,
              "shifted: zero mismatches at best offset")
        check(data["mismatch_cells"] == []
              and data["row_mismatches"] == [0, 0, 0]
              and data["col_mismatches"] == [0, 0, 0, 0],
              "shifted: empty cells and zero summaries")
        check(data["aligned_interlacing"] == matrix_a,
              "shifted: aligned B reproduces A")
        check(data["aligned_interlacing"] == shifted(matrix_b, 2, 2),
              "aligned matrix follows the documented shift convention")

        # C 与 A 仅差一个单元（(2,3) 多一个 1）：最佳偏移 (0,0)，1 处错位
        design_c = {
            "name": "C",
            "max_float": 4,
            "threading": [0, 1, 2, 3],
            "tie_up": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 1]],
            "treadling": [0, 1, 2],
        }
        cid = client.post("/designs", json=design_c).json()["id"]
        resp = client.post(f"/designs/{aid}/compare",
                           json={"other_design_id": cid})
        data = resp.json()
        check(data["row_offset"] == 0 and data["col_offset"] == 0,
              "one-cell diff: offset (0, 0)")
        check(data["mismatches"] == 1, "one-cell diff: 1 mismatch")
        check(abs(data["mismatch_ratio"] - 1 / 12) < 1e-9,
              "one-cell diff: ratio 1/12")
        check(data["mismatch_cells"] == [{"row": 2, "col": 3}],
              "one-cell diff: mismatch coordinate (2, 3)")
        check(data["row_mismatches"] == [0, 0, 1],
              "one-cell diff: row summary")
        check(data["col_mismatches"] == [0, 0, 0, 1],
              "one-cell diff: col summary")
        check(data["aligned_interlacing"][2][3] == 1,
              "offset (0, 0): aligned matrix is C itself")

        # 平局：平纹 4x4 与错位一纬的平纹有多个零错位偏移，
        # 取行偏移再列偏移最小者 (0, 1)
        plain = {
            "name": "plain",
            "max_float": 2,
            "threading": [0, 1, 0, 1],
            "tie_up": [[1, 0], [0, 1]],
            "treadling": [0, 1, 0, 1],
        }
        plain_shifted = dict(plain, name="plain shifted", treadling=[1, 0, 1, 0])
        pid = client.post("/designs", json=plain).json()["id"]
        sid = client.post("/designs", json=plain_shifted).json()["id"]
        resp = client.post(f"/designs/{pid}/compare",
                           json={"other_design_id": sid})
        data = resp.json()
        check(data["mismatches"] == 0,
              "plain weave: zero-mismatch alignment exists")
        check(data["row_offset"] == 0 and data["col_offset"] == 1,
              "tie broken by smallest row then col offset")

        # 尺寸不一致 -> 400（A 为 3x4，平纹为 4x4）
        resp = client.post(f"/designs/{aid}/compare",
                           json={"other_design_id": pid})
        check(resp.status_code == 400, "size mismatch returns 400")
        check("size mismatch" in resp.json()["detail"],
              "400 detail mentions size mismatch")

        # 接口只读：比对前后两份设计与设计总数均不变
        before_a = client.get(f"/designs/{aid}").json()
        before_b = client.get(f"/designs/{bid}").json()
        count_before = len(client.get("/designs").json())
        client.post(f"/designs/{aid}/compare", json={"other_design_id": bid})
        check(client.get(f"/designs/{aid}").json() == before_a,
              "compare does not modify the base design")
        check(client.get(f"/designs/{bid}").json() == before_b,
              "compare does not modify the other design")
        check(len(client.get("/designs").json()) == count_before,
              "compare does not insert new designs")


if __name__ == "__main__":
    test_compare_endpoint()
    try:
        os.unlink(_TMP_DB.name)
    except OSError:
        pass
    print("all API tests passed")
