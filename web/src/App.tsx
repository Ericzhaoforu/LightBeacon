import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import type { EffectMode, Layout, NodeView } from "./types";

const MODES: Array<{ mode: EffectMode; label: string; tone: string }> = [
  { mode: "OFF", label: "熄灭", tone: "off" },
  { mode: "BLINK_RED", label: "闪烁红", tone: "red" },
  { mode: "BLINK_GREEN", label: "闪烁绿", tone: "green" },
  { mode: "BLINK_BLUE", label: "闪烁蓝", tone: "blue" },
  { mode: "SOLID_BLUE", label: "常亮蓝", tone: "blue" },
];

type DragSelection = { anchor: number; current: number; base: Set<number> };

export function rectangleSelection(drag: DragSelection, columns: number): Set<number> {
  const result = new Set(drag.base);
  const ar = Math.floor(drag.anchor / columns);
  const ac = drag.anchor % columns;
  const cr = Math.floor(drag.current / columns);
  const cc = drag.current % columns;
  for (let row = Math.min(ar, cr); row <= Math.max(ar, cr); row += 1) {
    for (let column = Math.min(ac, cc); column <= Math.max(ac, cc); column += 1) {
      result.add(row * columns + column);
    }
  }
  return result;
}

function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(password);
      onSuccess();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="brand-mark" aria-hidden="true"><span /><span /><span /></div>
        <p className="eyebrow">PRIVATE LAN CONTROL</p>
        <h1>LightBeacon</h1>
        <p className="login-copy">户外灯光点阵控制台。此入口仅面向现场管理员。</p>
        <form onSubmit={submit}>
          <label htmlFor="password">管理员密码</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary wide" disabled={busy || !password}>
            {busy ? "正在验证…" : "进入控制台"}
          </button>
        </form>
      </section>
    </main>
  );
}

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [nodes, setNodes] = useState<NodeView[]>([]);
  const [layout, setLayout] = useState<Layout>({ rows: 4, columns: 4, cells: [] });
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [drag, setDrag] = useState<DragSelection | null>(null);
  const [editLayout, setEditLayout] = useState(false);
  const [mode, setMode] = useState<EffectMode>("BLINK_BLUE");
  const [frequency, setFrequency] = useState(1);
  const [brightness, setBrightness] = useState(25);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("等待操作");
  const [connection, setConnection] = useState<"live" | "retrying">("retrying");
  const [tab, setTab] = useState<"control" | "ota">("control");
  const [firmware, setFirmware] = useState<File | null>(null);
  const [firmwareVersion, setFirmwareVersion] = useState("");
  const [otaStatus, setOtaStatus] = useState("");

  const nodesById = useMemo(() => {
    const map = new Map<string, NodeView>();
    for (const node of nodes) {
      if (!node.id_conflict) map.set(node.node_id, node);
    }
    return map;
  }, [nodes]);

  const cellBindings = useMemo(() => {
    const map = new Map<number, string>();
    for (const cell of layout.cells) {
      if (cell.node_id) map.set(cell.row * layout.columns + cell.column, cell.node_id);
    }
    return map;
  }, [layout]);

  const visibleSelection = useMemo(
    () => (drag ? rectangleSelection(drag, layout.columns) : selection),
    [drag, layout.columns, selection],
  );

  const selectedNodeIds = useMemo(
    () => Array.from(visibleSelection).map((index) => cellBindings.get(index)).filter((value): value is string => Boolean(value)),
    [cellBindings, visibleSelection],
  );

  const onlineCount = nodes.filter((node) => node.online).length;
  const conflictCount = nodes.filter((node) => node.id_conflict).length;

  async function load() {
    try {
      const [nodeData, layoutData] = await Promise.all([api.nodes(), api.layout()]);
      setNodes(nodeData);
      setLayout(layoutData);
      setAuthenticated(true);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) setAuthenticated(false);
      else setMessage(reason instanceof Error ? reason.message : "无法连接主机服务");
    }
  }

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!authenticated) return;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let stopped = false;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/api/v1/events`);
      socket.onopen = () => setConnection("live");
      socket.onclose = () => {
        setConnection("retrying");
        if (!stopped) retry = window.setTimeout(connect, 1500);
      };
      socket.onmessage = (event) => {
        const update = JSON.parse(event.data) as Record<string, unknown>;
        if (update.type === "snapshot") setNodes(update.nodes as NodeView[]);
        if (["node.discovered", "node.updated", "node.offline"].includes(String(update.type))) {
          const node = update.node as NodeView;
          setNodes((current) => [...current.filter((item) => item.mac !== node.mac), node]);
        }
        if (update.type === "command.completed") setMessage(`命令 ${update.sequence} 已完成`);
        if (update.type === "ota.updated") setOtaStatus(`升级任务：${update.state}`);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) window.clearTimeout(retry);
      socket?.close();
    };
  }, [authenticated]);

  useEffect(() => {
    if (!drag) return;
    const finish = () => {
      setSelection(rectangleSelection(drag, layout.columns));
      setDrag(null);
    };
    window.addEventListener("pointerup", finish, { once: true });
    return () => window.removeEventListener("pointerup", finish);
  }, [drag, layout.columns]);

  function bindCell(index: number, nodeId: string) {
    const row = Math.floor(index / layout.columns);
    const column = index % layout.columns;
    setLayout((current) => ({
      ...current,
      cells: [
        ...current.cells.filter(
          (cell) => !(cell.row === row && cell.column === column) && (!nodeId || cell.node_id !== nodeId),
        ),
        ...(nodeId ? [{ row, column, node_id: nodeId }] : []),
      ],
    }));
  }

  async function saveLayout() {
    setBusy(true);
    try {
      const saved = await api.saveLayout(layout);
      setLayout(saved);
      setEditLayout(false);
      setMessage("二维布局已保存");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function sendEffect() {
    if (!selectedNodeIds.length) return setMessage("请先选择至少一个已绑定节点");
    setBusy(true);
    try {
      const period = mode.startsWith("BLINK_") ? Math.round(1000 / frequency) : 0;
      const result = await api.effect(selectedNodeIds, mode, period, brightness);
      const ok = Object.values(result.results).filter((value) => value === "accepted").length;
      setMessage(`命令 ${result.sequence}：${ok}/${selectedNodeIds.length} 个节点接受`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "灯效下发失败");
    } finally {
      setBusy(false);
    }
  }

  async function allOff() {
    setBusy(true);
    try {
      await api.allOff();
      setMessage("紧急全灭已广播三次");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "全灭命令失败");
    } finally {
      setBusy(false);
    }
  }

  async function startOta(event: React.FormEvent) {
    event.preventDefault();
    if (!firmware || !firmwareVersion || !selectedNodeIds.length) return;
    setBusy(true);
    try {
      const job = await api.ota(firmware, selectedNodeIds, firmwareVersion);
      setOtaStatus(`任务 ${job.job_id.slice(0, 8)} 已排队，SHA-256 ${job.sha256.slice(0, 12)}…`);
    } catch (reason) {
      setOtaStatus(reason instanceof Error ? reason.message : "OTA 创建失败");
    } finally {
      setBusy(false);
    }
  }

  if (authenticated === null) return <main className="loading">正在连接 LightBeacon 主机…</main>;
  if (!authenticated) return <Login onSuccess={() => void load()} />;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark compact" aria-hidden="true"><span /><span /><span /></div>
          <div><p>LIGHTBEACON</p><h1>现场控制台</h1></div>
        </div>
        <div className="header-status">
          <span className={`connection ${connection}`}><i />{connection === "live" ? "实时连接" : "正在重连"}</span>
          <span><strong>{onlineCount}</strong> 在线</span>
          <span><strong>{nodes.length - onlineCount}</strong> 离线</span>
          {conflictCount > 0 && <span className="danger-text"><strong>{conflictCount}</strong> 冲突</span>}
        </div>
        <button className="emergency" onClick={() => void allOff()} disabled={busy}>紧急全灭</button>
      </header>

      <nav className="tabs" aria-label="控制台页面">
        <button className={tab === "control" ? "active" : ""} onClick={() => setTab("control")}>点阵控制</button>
        <button className={tab === "ota" ? "active" : ""} onClick={() => setTab("ota")}>固件升级</button>
        <button className="logout" onClick={async () => { await api.logout(); setAuthenticated(false); }}>退出</button>
      </nav>

      <main className="workspace">
        <section className="stage-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">FIELD LAYOUT</p><h2>现场点阵</h2></div>
            <div className="layout-tools">
              {editLayout && <>
                <label>行<input type="number" min="1" max="50" value={layout.rows} onChange={(e) => setLayout({ ...layout, rows: Number(e.target.value), cells: [] })} /></label>
                <label>列<input type="number" min="1" max="50" value={layout.columns} onChange={(e) => setLayout({ ...layout, columns: Number(e.target.value), cells: [] })} /></label>
              </>}
              <button className="secondary" onClick={() => editLayout ? void saveLayout() : setEditLayout(true)} disabled={busy}>
                {editLayout ? "保存布局" : "编辑布局"}
              </button>
            </div>
          </div>

          <div
            className={`beacon-grid ${editLayout ? "editing" : ""}`}
            style={{ gridTemplateColumns: `repeat(${layout.columns}, minmax(86px, 1fr))` }}
            onPointerLeave={() => undefined}
          >
            {Array.from({ length: layout.rows * layout.columns }, (_, index) => {
              const nodeId = cellBindings.get(index);
              const node = nodeId ? nodesById.get(nodeId) : undefined;
              const selected = visibleSelection.has(index);
              return (
                <div
                  key={index}
                  className={`beacon-cell ${selected ? "selected" : ""} ${node?.online ? "online" : "offline"}`}
                  data-mode={node?.mode ?? "OFF"}
                  onPointerDown={(event) => {
                    if (editLayout) return;
                    event.preventDefault();
                    setDrag({ anchor: index, current: index, base: event.ctrlKey ? new Set(selection) : new Set() });
                  }}
                  onPointerEnter={() => drag && !editLayout && setDrag({ ...drag, current: index })}
                >
                  {editLayout ? (
                    <select value={nodeId ?? ""} onChange={(event) => bindCell(index, event.target.value)} aria-label={`绑定第 ${index + 1} 个格子`}>
                      <option value="">未绑定</option>
                      {nodes.map((item) => <option key={item.mac} value={item.node_id}>{item.node_id}</option>)}
                    </select>
                  ) : nodeId ? (
                    <>
                      <div className="beacon-light"><span /></div>
                      <strong>{nodeId}</strong>
                      <small>{node ? `${node.rssi} dBm · ${node.actual_brightness}%` : "未发现"}</small>
                      {node?.id_conflict && <b className="badge danger">ID 冲突</b>}
                    </>
                  ) : <span className="empty-cell">＋<small>空位</small></span>}
                </div>
              );
            })}
          </div>
          <footer className="stage-footer">
            <span>{selectedNodeIds.length} 个已绑定节点被选中</span>
            <button className="text-button" onClick={() => setSelection(new Set(Array.from(cellBindings.keys())))}>全选已绑定</button>
            <button className="text-button" onClick={() => setSelection(new Set())}>清除选择</button>
            <span className="message">{message}</span>
          </footer>
        </section>

        <aside className="control-panel">
          {tab === "control" ? (
            <>
              <div className="panel-heading"><div><p className="eyebrow">EFFECT COMMAND</p><h2>灯效设置</h2></div></div>
              <div className="mode-list">
                {MODES.map((item) => (
                  <button key={item.mode} className={mode === item.mode ? "active" : ""} data-tone={item.tone} onClick={() => setMode(item.mode)}>
                    <i /><span>{item.label}</span><small>{item.mode}</small>
                  </button>
                ))}
              </div>
              <div className="range-control">
                <label><span>闪烁频率</span><strong>{frequency.toFixed(1)} Hz</strong></label>
                <input type="range" min="0.1" max="5" step="0.1" value={frequency} disabled={!mode.startsWith("BLINK_")} onChange={(event) => setFrequency(Number(event.target.value))} />
                <small>50% 占空比 · 周期 {Math.round(1000 / frequency)} ms</small>
              </div>
              <div className="range-control">
                <label><span>请求亮度</span><strong>{brightness}%</strong></label>
                <input type="range" min="1" max="100" value={brightness} onChange={(event) => setBrightness(Number(event.target.value))} />
                <small>节点默认安全上限 25%</small>
              </div>
              <button className="primary wide send" onClick={() => void sendEffect()} disabled={busy || !selectedNodeIds.length}>
                {busy ? "正在下发…" : `应用到 ${selectedNodeIds.length} 个节点`}
              </button>
            </>
          ) : (
            <>
              <div className="panel-heading"><div><p className="eyebrow">SIGNED OTA</p><h2>固件升级</h2></div></div>
              <form className="ota-form" onSubmit={startOta}>
                <label>版本号<input value={firmwareVersion} onChange={(event) => setFirmwareVersion(event.target.value)} placeholder="例如 1.0.1" /></label>
                <label className="file-drop">
                  <input type="file" accept=".bin,application/octet-stream" onChange={(event) => setFirmware(event.target.files?.[0] ?? null)} />
                  <strong>{firmware?.name ?? "选择签名 ESP32 固件"}</strong>
                  <small>{firmware ? `${(firmware.size / 1024).toFixed(1)} KiB` : "仅接受 .bin 应用镜像"}</small>
                </label>
                <div className="ota-note">当前选择 {selectedNodeIds.length} 个节点；主机每批最多调度 5 个。</div>
                <button className="primary wide" disabled={busy || !firmware || !firmwareVersion || !selectedNodeIds.length}>创建升级任务</button>
                {otaStatus && <p className="ota-status">{otaStatus}</p>}
              </form>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}
