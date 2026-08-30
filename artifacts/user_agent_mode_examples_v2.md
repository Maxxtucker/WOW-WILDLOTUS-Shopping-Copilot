# User Agent V2 四个 Mode 实测示例

- 运行时间：2026-08-29
- Provider：DeepSeek
- Model：`deepseek-v4-flash`
- 命令：`python scripts/demo_user_agent_modes.py --samples 2 --seed 42`
- 范围：只调用 `ScenarioUserAgent.initial_message()`，不运行商品 Agent
- 安全：不包含 API key

## Sample 1：Browsing

```text
sample_id: public_0164
category: Watches Watch Bands

Mode 1:
I'm looking for Watches Watch Bands, but I'm still exploring.

Mode 2:
I am hoping to find Watches Watch Bands, but I am still looking around.

Mode 3:
I'm shopping for watch straps, and I'm still checking the details.

Mode 4:
I am look for watch straps, but I still checking what detail is important.
```

说明：Browsing 首轮没有披露隐藏的 `leather` 约束；Mode 2 保留原类别关键词，Mode 3 使用同义类别，Mode 4 保持探索意图并加入语法错误。

## Sample 2：Buying

```text
sample_id: public_0029
category: Sandals Flats
hard constraint: fabric

Mode 1:
I'm looking for Sandals Flats. A key requirement is: fabric.

Mode 2:
I'm searching for Sandals Flats. The main thing I need is fabric.

Mode 3:
I'm looking for flat sandals, and a key requirement is that they're made from textile.

Mode 4:
I am look for flat sandals, and I need the thing which is made from cloth textile material, okay.
```

说明：Mode 2 原样保留 `Sandals Flats` 和 `fabric`；Mode 3 将其改为 `flat sandals` 和 `textile`；Mode 4 通过语法错误和绕述保持相同意图。
