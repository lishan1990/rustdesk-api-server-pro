#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
ROOT = os.getcwd()
MAIN = os.path.join(ROOT, 'flutter', 'lib', 'main.dart')
SW = os.path.join(ROOT, 'flutter', 'lib', 'screenwall.dart')
def fail(m):
    print('screenwall patch: '+m, file=sys.stderr); sys.exit(1)
if not os.path.exists(MAIN): fail('main.dart not found')
s = open(MAIN, encoding='utf-8').read()
if "package:flutter_hbb/screenwall.dart" not in s:
    anchor = "import 'package:flutter_hbb/common.dart';"
    if anchor not in s: anchor = "import 'common.dart';"
    if anchor not in s: fail('import anchor not found')
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
SCREENWALL_SOURCE = "// RustDesk 屏幕墙模式（管理员专用监控墙）\n// 主进程以 --screenwall 启动，读取 exe 同目录 screenwall.json，\n// 开 N 个独立远程会话窗口，setFrame 摆成 N×N 宫格。点击任一窗口即可接管。\nimport 'dart:async';\nimport 'dart:convert';\nimport 'dart:io';\nimport 'dart:ui' as ui;\n\nimport 'package:desktop_multi_window/desktop_multi_window.dart';\nimport 'package:flutter/material.dart';\nimport 'package:window_manager/window_manager.dart';\n\nimport 'main.dart' show initEnv;\n\nclass _SWDevice {\n  final String id;\n  final String name;\n  final String password;\n  _SWDevice(this.id, this.name, this.password);\n  factory _SWDevice.fromJson(Map<String, dynamic> j) => _SWDevice(\n        (j['id'] ?? '').toString(),\n        (j['name'] ?? j['id'] ?? '').toString(),\n        (j['password'] ?? '').toString(),\n      );\n}\n\nString? _logFile;\nvoid _log(String msg) {\n  try {\n    _logFile ??= '${Directory.current.path}${Platform.pathSeparator}screenwall-debug.log';\n    final ts = DateTime.now().toIso8601String();\n    File(_logFile!).writeAsStringSync('[$ts] $msg\\n', mode: FileMode.append);\n  } catch (_) {}\n}\n\n/// 屏幕墙入口：由 main.dart 在 --screenwall 分支调用\n/// 调用前 main() 已执行 WidgetsFlutterBinding.ensureInitialized()\nFuture<void> runScreenWall() async {\n  try {\n    _log('screenwall: start, cwd=${Directory.current.path}');\n\n    // 完整初始化 FFI（与 runMainApp 相同），保证子窗口会话可用\n    await initEnv('main');\n    _log('screenwall: initEnv done');\n    await windowManager.ensureInitialized();\n    _log('screenwall: windowManager initialized');\n\n    // 关键：必须先 runApp，保证 root isolate / Flutter engine 存活，\n    // 否则 main() 返回后进程会立即退出（表现为双击 bat 闪退）。\n    runApp(const SizedBox.shrink());\n    await Future<void>.delayed(const Duration(milliseconds: 300));\n    _log('screenwall: runApp done');\n\n    // 配置文件：当前工作目录下的 screenwall.json\n    final cfgPath = '${Directory.current.path}${Platform.pathSeparator}screenwall.json';\n    _log('screenwall: config $cfgPath');\n    final content = await File(cfgPath).readAsString();\n    final cfg = jsonDecode(content) as Map<String, dynamic>;\n    final layout = (cfg['layout'] ?? '3x3').toString();\n    final parts = layout.split('x');\n    int cols = int.tryParse(parts[0]) ?? 3;\n    int rows = int.tryParse(parts.length > 1 ? parts[1] : '3') ?? 3;\n    if (cols < 1 || cols > 6) cols = 3;\n    if (rows < 1 || rows > 6) rows = 3;\n\n    final devices = <_SWDevice>[];\n    for (final d in (cfg['devices'] as List? ?? [])) {\n      final dev = _SWDevice.fromJson(d as Map<String, dynamic>);\n      if (dev.id.isNotEmpty) devices.add(dev);\n    }\n    if (devices.isEmpty) throw 'no devices in screenwall config';\n    _log('screenwall: config parsed devices=${devices.length} layout=${cols}x${rows}');\n\n    // 屏幕物理尺寸 / DPR → 逻辑像素\n    final ui.FlutterView view = WidgetsBinding.instance.platformDispatcher.views.first;\n    final ui.Size ps = view.physicalSize;\n    final double dpr = view.devicePixelRatio == 0 ? 1.0 : view.devicePixelRatio;\n    final double sw = ps.width / dpr;\n    final double sh = ps.height / dpr;\n    final double cw = sw / cols;\n    final double ch = sh / rows;\n    _log('screenwall: screen ${ps.width}x${ps.height} dpr=$dpr cell ${cw.toInt()}x${ch.toInt()}');\n\n    // 隐藏主窗口，只显示宫格子窗口\n    await windowManager.hide();\n    _log('screenwall: main window hidden');\n\n    int placed = 0;\n    for (int i = 0; i < devices.length && i < cols * rows; i++) {\n      final dev = devices[i];\n      // type=1 = WindowType.RemoteDesktop（enum: Main=0, RemoteDesktop=1）\n      final msg = jsonEncode(<String, dynamic>{\n        'type': 1,\n        'id': dev.id,\n        'password': dev.password,\n      });\n      final controller = await DesktopMultiWindow.createWindow(msg);\n      final int col = i % cols;\n      final int row = i ~/ cols;\n      await controller.setFrame(ui.Offset(col * cw, row * ch) & ui.Size(cw, ch));\n      await controller.setTitle('${dev.name} (${dev.id})');\n      placed++;\n      _log('screenwall: opened ${dev.name} -> window ${controller.windowId}');\n      await Future<void>.delayed(const Duration(milliseconds: 350));\n    }\n    _log('screenwall: $placed windows placed');\n\n    // 保持 root isolate 存活，避免 main() 结束后进程退出。\n    await Completer<void>().future;\n  } catch (e, st) {\n    _log('screenwall error: $e\\n$st');\n    try { await windowManager.show(); } catch (_) {}\n    // 出错时也保持进程，方便查看 screenwall-debug.log。\n    await Completer<void>().future;\n  }\n}\n"
with open(SW, 'w', encoding='utf-8') as f:
    f.write(SCREENWALL_SOURCE)
print('screenwall patch: screenwall.dart written')
