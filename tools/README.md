# 开发工具

这些都是开发/验证用的脚本，**运行程序本身不需要它们**。

## 界面相关

| 脚本 | 用途 |
|---|---|
| `checkGuiContract.py` | **改界面接口后必跑**。检查每个后端是否提供 main.py 需要的全部成员（取值器 / 方法 / 回调），并跑一遍状态切换冒烟测试。 |
| `ui-probe-mode.py` | Tk 后端的页面探针：`python tools/ui-probe-mode.py local\|live\|settings\|running`，把界面切到指定状态后停住，方便截图。 |
| `ui-probe-webview.py` | pywebview 探针（Windows）：起一个原生窗口，自动验证界面渲染（卡片数、控件数、切页后的按钮文案、输入框回传）。默认让窗口留着方便截图，要验「新版效果」切换就加 `--switch`（那一下会把窗口关掉重启）。 |
| `checkWebviewLogic.py` | pywebview 后端**无窗口**逻辑自检：设置暂存/保存/恢复默认、选路径规范化、按钮动作转发、状态回传、布局转换。不需要图形环境，改完随手跑。 |
| `checkAppStartup.py` | 真程序启动体检：跑一遍 main.py 的启动流程，检查启动后输入框是空的（防止程序日志混进去被当成待播报文字）。 |
| `checkPlayback.py` | 播放链路自检：两段音频同时播不会互相覆盖临时文件、播放会等满整段（防止尾音被截断）、连着点「播放」能同时响。最后会试放一段静音。 |
| `checkExport.py` | 导出链路自检：走一遍「导出」按钮真正执行的那段代码（选路径和弹窗用桩），检查生成的 wav 采样率/时长/有没有声音，并覆盖自动补 `.wav`、多级目录、空输入。macOS 和 Windows 都能跑，方便对比两端的产物。 |
| `checkBackendFallback.py` | 后端配对自检：平台配对（Windows 才摆「界面」卡片）、伪造「没有 WebView2」时应自动改用经典界面、点切换后的重启命令要对。 |
| `build-mac-app.sh` | 打成 macOS 的 .app（经典 + 原生两套界面装进同一个 app，素材打进包内，配置写用户目录）。会先 `swift build` 编译原生界面。`bash tools/build-mac-app.sh` |
| `make-icon.py` | 把 `assets/lizi.ico` 压进 `hzys/gui/icon_data.py`（程序运行和打包都不再需要单独的图标文件）。换了图标重跑一次即可。 |

三套界面，每个平台上都是两套，装在同一个程序里：

| 平台 | 新版 | 经典（兜底） |
|---|---|---|
| Windows | `webview`（pywebview + WebView2，同进程换后端） | `tk` |
| macOS | 原生界面（SwiftUI，同一个 .app 里的另一个可执行文件） | `tk` |

用哪套由 `data/settings.json` 的 `newUi` 决定（**默认 false = 经典界面**），
「高级设置 → 界面 → 新版效果」里可以随时切，切换会写回配置、下次启动照样记得。

macOS 上两套界面都装在同一个 .app 里（`release/mac-<架构>/<版本>-mac-<架构>.app`，
比如 `2026.9.20-mac-arm64.app`）：

```
Contents/MacOS/电棍棍活字       经典界面（tk），同时也是 --engine 引擎
Contents/MacOS/hzys-native     原生界面（SwiftUI）
```

切换是 execv 换进程——App 身份、Dock 图标不变，不会出现第二个 app
（实现在 `hzys/gui/nativeapp.py`，打包见 `tools/build-mac-app.sh`）。
原生界面自己不开窗口时是个引擎：用 `main.py --engine` 起进程、走
`hzys/gui/rpc_backend.py` 的 JSON 行协议。源码运行时原生界面要先
`cd mac && swift build -c release`。Windows 上强制指定后端可以用环境变量，
例如 `HZYS_GUI=webview python main.py`。

> 窗口标题栏和最大化/最小化/关闭按钮都用**各系统的原生实现**（Windows 在右上角，
> macOS 是左上角的红黄绿），所以拖动、双击最大化、贴边分屏这些都是系统自带的行为，
> 网页界面里不需要、也不应该再自己画一套。

> 关于 Windows 的 Mica：pywebview 的 Windows 后端是 WinForms，无边框 + 透明窗口上
> DWM 并不会真的把 Mica 铺到客户区（只会变成一块能看见后面窗口的玻璃），
> 所以网页后端在 Windows 上默认用不透明底色 + 圆角窗口。
> 想试验的话设 `HZYS_BACKDROP=mica`（Tk 后端同样支持这个变量）。

## 虚拟机（Windows）相关

这些脚本配合 Parallels 的 `prlctl` 使用，用来在真实的 Windows 里跑本程序和截图。
共享目录约定：Mac 上的项目目录以 `HZYS` 为名共享，虚拟机里是 `\\Mac\HZYS`，
本地工作副本是 `C:\hzys`。

| 脚本 | 用途 |
|---|---|
| `win-build.cmd` | 用 PyInstaller 打成 Windows 的 exe（素材打进包里，配置写 `%APPDATA%`）。**这个文件必须是纯 ASCII + CRLF**，否则 cmd 会解析错 |
| `win-setup.cmd` | 在虚拟机里安装依赖（等价于 `pip install -r requirements.txt`） |
| `win-run.cmd` | 同步项目到 `C:\hzys` 并启动程序（无控制台） |
| `win-debug.cmd` | 同上，但保留控制台并把输出写到共享目录里的 `win-run.log`。**桌面快捷方式就指向它** |
| `win-cmd.cmd` | 同步后执行任意命令，例如 `win-cmd.cmd tools\win-check.py` |
| `win-check.py` | 依赖体检：解释器架构、各模块能否导入 |
| `win-shot.ps1` | 截取指定标题的窗口（DPI 感知；显示器休眠时也能抓到内容） |
| `win-make-shortcut.ps1` | 在虚拟机桌面创建「电棍棍活字 调试」快捷方式（指向 `win-debug.cmd`，带图标）。虚拟机重装后跑一次即可 |

常用流程（在 Mac 上执行）：

```bash
prlctl exec "Windows 11" --current-user cmd /c '\\Mac\HZYS\tools\win-run.cmd'
prlctl exec "Windows 11" --current-user powershell -NoProfile -ExecutionPolicy Bypass \
  -File '\\Mac\HZYS\tools\win-shot.ps1' -Match 'ver.2026' -Out 'C:\hzys\shot.png'
```

重建桌面快捷方式：

```bash
prlctl exec "Windows 11" --current-user powershell -NoProfile -ExecutionPolicy Bypass \
  -File '\\Mac\HZYS\tools\win-make-shortcut.ps1' -Name "电棍棍活字 调试"
```
