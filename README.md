# retest-assembler

可复现的重考组卷库（纯 Python 标准库，无第三方依赖）。

## 功能

`assemble` 在满足全部硬约束的合法卷中，按字典序精确最小化三级成本：

1. 入选题中曾在历史卷出现过的题目数；
2. 入选题在所有历史卷中的出现次数之和（同一题在不同历史卷中重复计数）；
3. 入选题的随机成本之和（`SHA-256(f"{seed}:{题目ID}")` 按无符号大端整数解释）。

相同输入集合与 seed 必然得到相同结果，与题池、标签、历史卷的输入顺序无关。

## 硬约束

- 一份卷恰好 `count` 道不同的题；
- 每个主题、每个难度（1–5）的数量落在各自闭区间配额内；
- 每道入选题从自己的标签中选择且只选择一个计额主题；
- 包含全部必选题，不包含禁选题；
- 历史记录只影响成本，不是禁选规则。

## 用法

```python
from retest_assembler import (
    NO_SOLUTION, AssemblyRequest, Question, Quota, assemble,
)

request = AssemblyRequest(
    questions=(
        Question("q1", 1, frozenset({"代数", "几何"})),
        Question("q2", 2, frozenset({"代数"})),
        Question("q3", 2, frozenset({"几何"})),
    ),
    count=2,
    topic_quotas={"代数": Quota(1, 2), "几何": Quota(1, 1)},
    difficulty_quotas={1: Quota(0, 1), 2: Quota(1, 2)},
    required=frozenset({"q2"}),      # 必选题
    banned=frozenset(),              # 禁选题
    history=(frozenset({"q1", "q3"}),),  # 每套历史卷一个 ID 集合
    seed=7,
)

result = assemble(request)
if result is NO_SOLUTION:
    print("不存在合法卷")
else:
    for sel in result.selections:    # 按题目 ID 排序
        print(sel.question_id, "->", sel.counting_topic)
```

## 说明

- 输入不合法（重复题目 ID、难度超出 1–5、必选/禁选 ID 不在题池等）抛出
  `ValueError`；约束不可满足时返回单例 `NO_SOLUTION`。
- 未出现在配额表中的主题可作为计额主题且不受约束；难度同理。
- 算法为精确动态规划，状态为（已选题数， 各主题计数， 各难度计数），
  成本为精确整数三元组，绝不使用浮点或近似比较。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

覆盖：多标签题被迫改变计额归属的交叉配额实例（含必选/禁选）、单独可行
合起来无解的实例、小题池穷举枚举对照（含历史题不可避免场景）、输入打乱
后的可复现性、随机成本定义、历史多次出现分别计数等。
