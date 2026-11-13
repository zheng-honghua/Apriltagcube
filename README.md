# AprilTag 方块

在 macOS 上生成带 AprilTag 的方块。可按毫米设置方块边长、码图边长和黑色嵌件的深度，给六个面分别选择 ID，并拖动查看三维预览。支持 `tag36h11` 和 `tagStandard41h12`。

## 构建与运行

需要 macOS 14 或以上、Xcode Command Line Tools 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在终端进入仓库目录后运行：

```sh
./源码/安装与构建.command
```

脚本会在当前用户的 Application Support 目录安装 Python 3.13 和 Open CASCADE 运行环境（如果尚未安装），并在仓库根目录生成 `AprilTag方块.app`。双击打开即可。

## 导出和打印

- **STEP** 导出带颜色的 AP242 实体装配，适合在 CAD 中查看和编辑。
- **打印 3MF** 将白色方块和黑色码图作为同一个对象的两个零件导出。用 Bambu Studio 导入后，选择实际机型和喷嘴，把两个零件分配到对应的耗材，再切片。黑色嵌件与方块表面齐平。

[60 mm 双色示例](examples/AprilTag_ID0_60mm.3mf) 的六面均为 `tag36h11` ID 0，码图边长 50 mm，嵌入深度 0.8 mm。已用 Bambu Studio 的 P1S、0.4 mm 喷嘴和 0.2 mm 层高预设验证切片，首层和末层均有两色。使用其他参数时，请在切片预览中确认码图完整。

AprilTag 码表取自 [AprilRobotics AprilTag 3.4.5](https://github.com/AprilRobotics/apriltag/tree/v3.4.5)，许可见 [AprilTag-LICENSE.txt](源码/AprilTag-LICENSE.txt)。
