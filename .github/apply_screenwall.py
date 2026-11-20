#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
ROOT = os.getcwd()
MAIN = os.path.join(ROOT, 'flutter', 'lib', 'main.dart')
HOME = os.path.join(ROOT, 'flutter', 'lib', 'desktop', 'pages', 'desktop_home_page.dart')
SW = os.path.join(ROOT, 'flutter', 'lib', 'screenwall.dart')

def fail(m):
    print('screenwall patch: ' + m, file=sys.stderr); sys.exit(1)

# ---------- main.dart: import + --screenwall 分支 ----------
if not os.path.exists(MAIN): fail('main.dart not found')
s = open(MAIN, encoding='utf-8').read()
if "package:flutter_hbb/screenwall.dart" not in s:
    anchor = "import 'package:flutter_hbb/common/widgets/overlay.dart';"
    if anchor not in s:
        anchor = "import 'package:flutter_hbb/common.dart';"
    if anchor not in s:
        anchor = "import 'common.dart';"
    if anchor not in s: fail('main import anchor not found')
    s = s.replace(anchor, anchor + "\nimport 'package:flutter_hbb/screenwall.dart';", 1)
if "--screenwall" not in s:
    old = """  } else if (args.contains('--install')) {
    runInstallPage();
  } else {
    desktopType = DesktopType.main;"""
    new = """  } else if (args.isNotEmpty && args.first == '--screenwall') {
    desktopType = DesktopType.main;
    await runScreenWall();
  } else if (args.contains('--install')) {
    runInstallPage();
  } else {
    desktopType = DesktopType.main;"""
    if old not in s: fail('main branch anchor not found')
    s = s.replace(old, new, 1)
open(MAIN, 'w', encoding='utf-8').write(s)
print('screenwall patch: main.dart patched')

# ---------- desktop_home_page.dart: 主界面「屏幕墙」按钮 ----------
if not os.path.exists(HOME): fail('desktop_home_page.dart not found')
h = open(HOME, encoding='utf-8').read()
if "launchScreenWall" not in h:
    # 1) import screenwall.dart
    ia = "import 'package:flutter_hbb/consts.dart';"
    if ia not in h: fail('home import anchor not found')
    h = h.replace(ia, ia + "\nimport 'package:flutter_hbb/screenwall.dart' show launchScreenWall;", 1)
    # 2) 在 loadLogo() 之后插入按钮行
    ba = """      Align(
        alignment: Alignment.center,
        child: loadLogo(),
      ),
      buildTip(context),"""
    btn = """      Align(
        alignment: Alignment.center,
        child: loadLogo(),
      ),
      // >>> SCREENWALL_UI >>>
      Center(
        child: Container(
          margin: const EdgeInsets.only(left: 20, right: 11, top: 4, bottom: 4),
          child: OutlinedButton.icon(
            onPressed: () => launchScreenWall(),
            icon: const Icon(Icons.grid_view, size: 18),
            label: const Text('屏幕墙'),
          ),
        ),
      ),
      // <<< SCREENWALL_UI <<<
      buildTip(context),"""
    if ba not in h: fail('home button anchor not found')
    h = h.replace(ba, btn, 1)
open(HOME, 'w', encoding='utf-8').write(h)
print('screenwall patch: desktop_home_page.dart patched')

# ---------- screenwall.dart: 写入源码 ----------
SCREENWALL_SOURCE = "// RustDesk 屏幕墙模式（管理员专用监控墙）\n// 1) 主界面左侧面板出现「屏幕墙」按钮，点击后以 --screenwall 拉起独立进程；\n// 2) 该进程读取 screenwall.json（多候选路径），开 N 个独立远程会话窗口，\n//    setFrame 摆成 N×N 宫格。点击任一窗口即可接管。\nimport 'dart:async';\nimport 'dart:convert';\nimport 'dart:io';\nimport 'dart:ui' as ui;\n\nimport 'package:desktop_multi_window/desktop_multi_window.dart';\nimport 'package:flutter/material.dart';\nimport 'package:window_manager/window_manager.dart';\n\nimport 'main.dart' show initEnv;\n\nclass _SWDevice {\n  final String id;\n  final String name;\n  final String password;\n  _SWDevice(this.id, this.name, this.password);\n  factory _SWDevice.fromJson(Map<String, dynamic> j) => _SWDevice(\n        (j['id'] ?? '').toString(),\n        (j['name'] ?? j['id'] ?? '').toString(),\n        (j['password'] ?? '').toString(),\n      );\n}\n\nString? _logFile;\nList<String> _logDirs = const [];\n\nvoid _initLog() {\n  if (_logFile != null) return;\n  final dirs = <String>[Directory.current.path];\n  try {\n    dirs.add(File(Platform.resolvedExecutable).parent.path);\n  } catch (_) {}\n  if (Platform.isWindows) {\n    final appdata = Platform.environment['APPDATA'];\n    if (appdata != null) {\n      dirs.add('$appdata${Platform.pathSeparator}RDD3FDE6');\n      dirs.add('$appdata${Platform.pathSeparator}逍遥远控');\n    }\n  }\n  _logDirs = dirs;\n  for (final d in dirs) {\n    try {\n      final probe = '$d${Platform.pathSeparator}screenwall-debug.log';\n      File(probe).writeAsStringSync('', mode: FileMode.append);\n      _logFile = probe;\n      break;\n    } catch (_) {}\n  }\n}\n\nvoid _log(String msg) {\n  try {\n    _initLog();\n    final ts = DateTime.now().toIso8601String();\n    final line = '[$ts] $msg\\n';\n    if (_logFile != null) {\n      File(_logFile!).writeAsStringSync(line, mode: FileMode.append);\n    }\n    // 同时写入 exe 目录一份，便于从安装目录查看\n    try {\n      final exeDir = File(Platform.resolvedExecutable).parent.path;\n      if (exeDir != (_logFile == null ? '' : File(_logFile!).parent.path)) {\n        File('$exeDir${Platform.pathSeparator}screenwall-debug.log')\n            .writeAsStringSync(line, mode: FileMode.append);\n      }\n    } catch (_) {}\n  } catch (_) {}\n}\n\n/// 供主界面按钮调用：拉起一个独立的 --screenwall 进程。\n/// 用独立进程而非在当前进程切换，是为了避免与已运行主界面的 runApp 冲突；\n/// 且 core_main 的单实例转发白名单不含 --screenwall，能正常新起进程。\nFuture<void> launchScreenWall() async {\n  try {\n    _log('launch: requested');\n    final exe = Platform.resolvedExecutable;\n    await Process.start(exe, ['--screenwall'],\n        workingDirectory: Directory.current.path, mode: ProcessStartMode.detached);\n    _log('launch: spawned $exe --screenwall');\n  } catch (e, st) {\n    _log('launch error: $e\\n$st');\n  }\n}\n\n/// 多候选路径查找 screenwall.json，兼容：\n/// - bat 启动（工作目录 = 脚本目录）\n/// - 主界面按钮启动（工作目录 = 客户端启动目录，常为安装目录或 System32）\nString? _findConfig() {\n  final dirs = <String>[Directory.current.path];\n  try {\n    dirs.add(File(Platform.resolvedExecutable).parent.path);\n  } catch (_) {}\n  if (Platform.isWindows) {\n    final appdata = Platform.environment['APPDATA'];\n    if (appdata != null) {\n      for (final name in ['RDD3FDE6', '逍遥远控', 'RustDesk']) {\n        dirs.add('$appdata${Platform.pathSeparator}$name');\n      }\n    }\n    final user = Platform.environment['USERPROFILE'];\n    if (user != null) dirs.add('$user${Platform.pathSeparator}Documents');\n  }\n  for (final d in dirs) {\n    final p = '$d${Platform.pathSeparator}screenwall.json';\n    try {\n      if (File(p).existsSync()) return p;\n    } catch (_) {}\n  }\n  return null;\n}\n\n/// 屏幕墙入口：由 main.dart 在 --screenwall 分支调用\n/// 调用前 main() 已执行 WidgetsFlutterBinding.ensureInitialized()\nFuture<void> runScreenWall() async {\n  try {\n    _log('screenwall: start, cwd=${Directory.current.path}');\n\n    // 完整初始化 FFI（与 runMainApp 相同），保证子窗口会话可用\n    await initEnv('main');\n    _log('screenwall: initEnv done');\n    await windowManager.ensureInitialized();\n    _log('screenwall: windowManager initialized');\n\n    // 关键：必须先 runApp，保证 root isolate / Flutter engine 存活，\n    // 否则 main() 返回后进程会立即退出（表现为闪退）。\n    runApp(const SizedBox.shrink());\n    await Future<void>.delayed(const Duration(milliseconds: 300));\n    _log('screenwall: runApp done');\n\n    final cfgPath = _findConfig();\n    if (cfgPath == null) {\n      throw 'screenwall.json not found. Looked in cwd / exe dir / AppDATA / Documents';\n    }\n    _log('screenwall: config $cfgPath');\n    final content = await File(cfgPath).readAsString();\n    final cfg = jsonDecode(content) as Map<String, dynamic>;\n    final layout = (cfg['layout'] ?? '3x3').toString();\n    final parts = layout.split('x');\n    int cols = int.tryParse(parts[0]) ?? 3;\n    int rows = int.tryParse(parts.length > 1 ? parts[1] : '3') ?? 3;\n    if (cols < 1 || cols > 6) cols = 3;\n    if (rows < 1 || rows > 6) rows = 3;\n\n    final devices = <_SWDevice>[];\n    for (final d in (cfg['devices'] as List? ?? [])) {\n      final dev = _SWDevice.fromJson(d as Map<String, dynamic>);\n      if (dev.id.isNotEmpty) devices.add(dev);\n    }\n    if (devices.isEmpty) throw 'no devices in screenwall config';\n    _log('screenwall: config parsed devices=${devices.length} layout=${cols}x${rows}');\n\n    // 屏幕物理尺寸 / DPR → 逻辑像素\n    final ui.FlutterView view = WidgetsBinding.instance.platformDispatcher.views.first;\n    final ui.Size ps = view.physicalSize;\n    final double dpr = view.devicePixelRatio == 0 ? 1.0 : view.devicePixelRatio;\n    final double sw = ps.width / dpr;\n    final double sh = ps.height / dpr;\n    final double cw = sw / cols;\n    final double ch = sh / rows;\n    _log('screenwall: screen ${ps.width}x${ps.height} dpr=$dpr cell ${cw.toInt()}x${ch.toInt()}');\n\n    // 隐藏主窗口，只显示宫格子窗口\n    await windowManager.hide();\n    _log('screenwall: main window hidden');\n\n    int placed = 0;\n    for (int i = 0; i < devices.length && i < cols * rows; i++) {\n      final dev = devices[i];\n      // type=1 = WindowType.RemoteDesktop（enum: Main=0, RemoteDesktop=1）\n      final msg = jsonEncode(<String, dynamic>{\n        'type': 1,\n        'id': dev.id,\n        'password': dev.password,\n      });\n      final controller = await DesktopMultiWindow.createWindow(msg);\n      final int col = i % cols;\n      final int row = i ~/ cols;\n      await controller.setFrame(ui.Offset(col * cw, row * ch) & ui.Size(cw, ch));\n      await controller.setTitle('${dev.name} (${dev.id})');\n      placed++;\n      _log('screenwall: opened ${dev.name} -> window ${controller.windowId}');\n      await Future<void>.delayed(const Duration(milliseconds: 350));\n    }\n    _log('screenwall: $placed windows placed');\n\n    // 保持 root isolate 存活，避免 main() 结束后进程退出。\n    await Completer<void>().future;\n  } catch (e, st) {\n    _log('screenwall error: $e\\n$st');\n    try { await windowManager.show(); } catch (_) {}\n    // 出错时也保持进程，方便查看 screenwall-debug.log。\n    await Completer<void>().future;\n  }\n}\n"

with open(SW, 'w', encoding='utf-8') as f:
    f.write(SCREENWALL_SOURCE)
print('screenwall patch: screenwall.dart written')
