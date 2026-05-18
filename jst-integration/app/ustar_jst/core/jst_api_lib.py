"""
聚水潭新版 API 封装（基于 JSTBaseClient）
JST API Library v2 — 使用统一基类

⚠️ 已废弃，请使用 core.jst_client.JSTClient
此文件保留用于兼容，逐步迁移。
"""
# 兼容重定向
from .jst_client import JSTClient as JSTClientBase

class JSTClient(JSTClientBase):
    """聚水潭新版 API 客户端（openapi.jushuitan.com）"""
    pass

def main():
    """保留测试入口，透传到统一 SDK"""
    from .jst_client import JSTClient
    client = JSTClient()

    print("=== 聚水潭API测试 (v2 基类版) ===\n")

    print("0. 健康检查:")
    health = client.health_check()
    print(f"   -> {health}")

    print("1. 店铺列表:")
    shops = client.query_shops()
    print(f"   -> {len(shops)} 条")

    print("2. 供应商:")
    suppliers = client.query_suppliers()
    print(f"   -> {len(suppliers)} 条")

    print("3. 物流公司:")
    logistics = client.query_logistics_companies()
    print(f"   -> {len(logistics)} 条")

    print("4. 商品类目:")
    categories = client.query_categories()
    print(f"   -> {len(categories)} 条")

    print("5. 虚拟仓:")
    vws = client.query_virtual_warehouses()
    print(f"   -> {len(vws)} 条")

    print("\n6. 采购入库流程测试:")
    try:
        result = client.purchase_flow("7613287226679ZZ2", 5)
        print(f"   -> po_id={result['po_id']}, status={result['status']}")
    except Exception as e:
        print(f"   -> {e}")


if __name__ == "__main__":
    main()
