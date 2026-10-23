import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import "./style.css";
const api = axios.create({ baseURL: "/api" });
api.interceptors.request.use((c) => {
  const s = localStorage.getItem("teleport_session");
  if (s) c.headers.set("X-Session-Id", s);
  return c;
});
type Node = {
  id: number;
  hostname: string;
  node_id?: string;
  address?: string;
  labels?: Record<string, string>;
  last_scan?: string;
  status?: string;
  scan_status?: string;
};
const statusOf = (n: Node) => n.status || n.scan_status || "UNKNOWN";
const statusLabel: Record<string, string> = {
  SAFE: "AN TOÀN",
  WARNING: "CẢNH BÁO",
  ERROR: "LỖI",
  UNREACHABLE: "KHÔNG KẾT NỐI",
  UNKNOWN: "CHƯA RÕ",
  QUEUED: "ĐANG CHỜ",
  PENDING: "ĐANG CHỜ",
  SCANNING: "ĐANG QUÉT",
  RUNNING: "ĐANG CHẠY",
  COMPLETED: "HOÀN THÀNH",
  FAILED: "THẤT BẠI",
  CANCELLED: "ĐÃ HỦY",
  CONFIGURED: "ĐÃ CẤU HÌNH",
  NOT_CONFIGURED: "CHƯA CẤU HÌNH",
  DETECTED: "ĐÃ PHÁT HIỆN",
  NOT_DETECTED: "KHÔNG PHÁT HIỆN",
  NOT_SCANNED: "CHƯA QUÉT",
  ONLINE: "TRỰC TUYẾN",
  OFFLINE: "NGOẠI TUYẾN",
};
const Badge = ({ status }: { status: string }) => {
  const normalized = status || "UNKNOWN";
  return (
    <span className={"badge " + normalized} aria-label={`Trạng thái: ${statusLabel[normalized] || normalized}`}>
      {statusLabel[normalized] || normalized}
    </span>
  );
};
const Card = ({ title, value }: { title: string; value: React.ReactNode }) => (
  <div className="card">
    <small>{title}</small>
    <strong>{value ?? "—"}</strong>
  </div>
);
const time = (v?: string) => (v ? new Date(v).toLocaleString("vi-VN") : "Chưa có");
async function download(url: string) {
  const r = await api.get(url, { responseType: "blob" }),
    d = r.headers["content-disposition"] || "",
    name =
      d.match(/filename=\"?([^\";]+)/)?.[1] || "teleport_cgroup_report.xlsx",
    u = URL.createObjectURL(r.data),
    a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  URL.revokeObjectURL(u);
}
type AppRole = "VIEWER" | "OPERATOR" | "ADMIN";

function Dialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = `dialog-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  useEffect(() => {
    const dialog = dialogRef.current;
    const first = dialog?.querySelector<HTMLElement>("[autofocus], input, select, button:not([disabled])");
    first?.focus();
  }, []);
  const trapFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      ) || [],
    );
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <div className="modal" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={dialogRef} className="modal-card" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={trapFocus}>
        <h3 id={titleId}>{title}</h3>
        {children}
      </div>
    </div>
  );
}
function Login({ ok }: { ok: (role: AppRole) => void }) {
  const [f, setF] = useState({
      proxy: "",
      tsh_version: "16.4",
      username: "",
      password: "",
      otp: "",
    }),
    [e, setE] = useState("");
  const submit = async (x: React.FormEvent) => {
    x.preventDefault();
    setE("");
    try {
      const r = await api.post("/auth/login", f);
      localStorage.setItem("teleport_session", r.data.session_id);
      ok((r.data.role || "VIEWER") as AppRole);
    } catch (a: any) {
      setE(a.response?.data?.detail || "Teleport login failed.");
    }
  };
  return (
    <main className="login">
      <form onSubmit={submit}>
        <h1>Teleport Cgroup Scanner</h1>
        <label>
          Teleport Proxy
          <input
            required
            value={f.proxy}
            onChange={(x) => setF({ ...f, proxy: x.target.value })}
          />
        </label>
        <label>
          TSH Version
          <select
            value={f.tsh_version}
            onChange={(x) => setF({ ...f, tsh_version: x.target.value })}
          >
            <option>13.4</option>
            <option>14.4</option>
            <option>16.4</option>
          </select>
        </label>
        <label>
          Username
          <input
            required
            value={f.username}
            onChange={(x) => setF({ ...f, username: x.target.value })}
          />
        </label>
        <label>
          Password
          <input
            required
            type="password"
            value={f.password}
            onChange={(x) => setF({ ...f, password: x.target.value })}
          />
        </label>
        <label>
          OTP
          <input
            value={f.otp}
            onChange={(x) => setF({ ...f, otp: x.target.value })}
          />
        </label>
        {e && <p className="error">{e}</p>}
        <button>LOGIN</button>
      </form>
    </main>
  );
}
function Labels({ labels }: { labels?: Record<string, string> }) {
  const values = Object.entries(labels || {}).map(([k, v]) => `${k}=${v}`);
  return (
    <div className="label-list" title={values.join("\n")}>
      {values.slice(0, 3).map((x) => (
        <span key={x}>{x}</span>
      ))}
      {values.length > 3 && <span>+{values.length - 3}</span>}
    </div>
  );
}
function Nodes({
  openReport,
  role,
  scanMode = false,
}: {
  openReport: (id: number) => void;
  role: AppRole;
  scanMode?: boolean;
}) {
  const [search, setSearch] = useState(""),
    [term, setTerm] = useState(""),
    [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(50),
    [selected, setSelected] = useState<Set<number>>(new Set()),
    [jobs, setJobs] = useState<Record<number, string>>({}),
    [automatic, setAutomatic] = useState(
      localStorage.getItem("node_auto_refresh") || "off",
    ),
    [notice, setNotice] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => {
      setTerm(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(
    () => localStorage.setItem("node_auto_refresh", automatic),
    [automatic],
  );
  const nodes = useQuery({
    queryKey: ["nodes", term, page, pageSize],
    queryFn: () =>
      api
        .get("/nodes", { params: { search: term, page, page_size: pageSize } })
        .then((r) => r.data),
  });
  const refresh = async () => {
      setNotice("Đang tải lại node…");
    try {
      await api.post("/nodes/refresh");
      await nodes.refetch();
      setNotice("Đã tải lại danh sách node.");
    } catch {
      setNotice("Không thể tải lại danh sách node.");
    }
  };
  useEffect(() => {
    const m = Number(automatic);
    if (!m) return;
    const t = window.setInterval(refresh, m * 60000);
    return () => clearInterval(t);
  }, [automatic]);
  const active = useMemo(() => new Set(Object.keys(jobs).map(Number)), [jobs]);
  useEffect(() => {
    const ids = [...new Set(Object.values(jobs))];
    if (!ids.length) return;
    const t = window.setInterval(async () => {
      const done: string[] = [];
      await Promise.all(
        ids.map(async (id) => {
          try {
            const r = await api.get(`/scan/${id}`);
            if (["COMPLETED", "FAILED", "CANCELLED"].includes(r.data.status))
              done.push(id);
          } catch {
            done.push(id);
          }
        }),
      );
      if (done.length) {
        setJobs((x) =>
          Object.fromEntries(
            Object.entries(x).filter(([, job]) => !done.includes(job)),
          ),
        );
        await nodes.refetch();
      }
    }, 2000);
    return () => clearInterval(t);
  }, [jobs]);
  const rows: Node[] = nodes.data?.items || [];
  const all = rows.length > 0 && rows.every((n) => selected.has(n.id));
  const toggle = (id: number) =>
    setSelected((x) => {
      const y = new Set(x);
      y.has(id) ? y.delete(id) : y.add(id);
      return y;
    });
  const togglePage = () =>
    setSelected((x) => {
      const y = new Set(x);
      rows.forEach((n) => (all ? y.delete(n.id) : y.add(n.id)));
      return y;
    });
  const scan = async (ids: number[]) => {
    const clean = [...new Set(ids)];
    if (!clean.length) return;
    try {
      const r =
        clean.length === 1
          ? await api.post(`/nodes/${clean[0]}/scan`)
          : await api.post("/scan", { node_ids: clean });
      setJobs((x) =>
        Object.fromEntries([
          ...Object.entries(x),
          ...clean.map((id) => [id, r.data.job_id]),
        ]),
      );
      setSelected(new Set());
      await nodes.refetch();
    } catch (e: any) {
      setNotice(e.response?.data?.detail || "Unable to start scan.");
    }
  };
  const total = nodes.data?.total || 0,
    pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <section>
      <header>
        <h1>{scanMode ? "Quét tiến trình" : "Nodes"}</h1>
        <div className="refresh-control">
          <label>
            Tự động tải lại
            <select
              value={automatic}
              onChange={(e) => setAutomatic(e.target.value)}
            >
              <option value="1">1 phút</option>
              <option value="3">3 phút</option>
              <option value="5">5 phút</option>
              <option value="off">Tắt</option>
            </select>
          </label>
          <button onClick={refresh}>Tải lại</button>
        </div>
      </header>
      <div className="cards">
        <Card title="Tổng số node" value={total} />
        <Card title="Lần tải gần nhất" value={time(nodes.data?.last_refresh)} />
      </div>
      <input
        className="node-search"
        aria-label="Tìm node"
        placeholder="Tìm hostname, tên node, IP hoặc nhãn…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {notice && <p className="notice">{notice}</p>}
      {scanMode && <div className="selection-bar">
        <span>
          Đã chọn {selected.size} node
        </span>
        <button disabled={!selected.size || role === "VIEWER"} title={role === "VIEWER" ? "Viewer chỉ có quyền xem" : undefined} onClick={() => scan([...selected])}>
          Quét đã chọn{selected.size ? ` (${selected.size})` : ""}
        </button>
        <button
          className="secondary"
          disabled={!selected.size}
          onClick={() => setSelected(new Set())}
        >
          Bỏ chọn
        </button>
      </div>}
      {nodes.isLoading ? (
        <p>Đang tải node…</p>
      ) : nodes.isError ? (
        <p className="error">Không thể tải danh sách node.</p>
      ) : !rows.length ? (
        <p>Không tìm thấy node.</p>
      ) : (
        <table>
          <caption className="sr-only">Danh sách node Teleport và trạng thái quét gần nhất</caption>
          <thead>
            <tr>
              <th>
                <input
                  aria-label="Select current page"
                  type="checkbox"
                  checked={all}
                  ref={(e) => {
                    if (e)
                      e.indeterminate =
                        !all && rows.some((n) => selected.has(n.id));
                  }}
                  onChange={togglePage}
                />
              </th>
              <th scope="col">Hostname</th>
              <th scope="col">IP</th>
              <th scope="col">Nhãn</th>
              <th scope="col">Lần quét gần nhất</th>
              <th scope="col">Trạng thái</th>
              <th scope="col">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => {
              const pending = active.has(n.id),
                stored = statusOf(n),
                status =
                  pending && ["QUEUED", "SCANNING"].includes(stored)
                    ? stored
                    : pending
                      ? "SCANNING"
                      : stored;
              return (
                <tr key={n.id}>
                  <td>
                    <input
                      aria-label={"Select " + n.hostname}
                      type="checkbox"
                      checked={selected.has(n.id)}
                      onChange={() => toggle(n.id)}
                    />
                  </td>
                  <td>{n.hostname}</td>
                  <td>{n.address || "—"}</td>
                  <td>
                    <Labels labels={n.labels} />
                  </td>
                  <td>{time(n.last_scan)}</td>
                  <td>
                    {["SAFE", "WARNING", "ERROR"].includes(status) ? (
                      <button
                        className="status-link"
                        onClick={() => openReport(n.id)}
                      >
                        <Badge status={status} />
                      </button>
                    ) : (
                      <Badge status={status} />
                    )}
                  </td>
                  <td>
                    {scanMode && <button disabled={pending || role === "VIEWER"} title={role === "VIEWER" ? "Viewer chỉ có quyền xem" : undefined} onClick={() => scan([n.id])}>
                      {pending ? (
                        <>
                          <i className="spinner" />{" "}
                          {status === "QUEUED" ? "Đang chờ" : "Đang quét…"}
                        </>
                      ) : (
                        "Quét"
                      )}
                    </button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="pagination">
        <span>
          Hiển thị {total ? (page - 1) * pageSize + 1 : 0}–
          {Math.min(page * pageSize, total)} / {total}
        </span>
        <label>
          Số dòng/trang{" "}
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
          >
            <option>25</option>
            <option>50</option>
            <option>100</option>
          </select>
        </label>
        <button
          className="secondary"
          disabled={page === 1}
          onClick={() => setPage(page - 1)}
        >
          Trước
        </button>
        <span>
          Trang {page} / {pages}
        </span>
        <button
          className="secondary"
          disabled={page >= pages}
          onClick={() => setPage(page + 1)}
        >
          Sau
        </button>
      </div>
    </section>
  );
}
function Report({
  initialHost,
  onBack,
}: {
  initialHost?: number;
  onBack?: () => void;
}) {
  const [q, setQ] = useState(""),
    [st, setSt] = useState(""),
    [page, setPage] = useState(1),
    [host, setHost] = useState<number | undefined>(initialHost),
    [scan, setScan] = useState<string>();
  useEffect(() => setHost(initialHost), [initialHost]);
  const summary = useQuery({
      queryKey: ["report-summary"],
      queryFn: () => api.get("/reports/summary").then((r) => r.data),
    }),
    hosts = useQuery({
      queryKey: ["report-hosts", q, st, page],
      queryFn: () =>
        api
          .get("/reports/hosts", {
            params: {
              search: q || undefined,
              status: st || undefined,
              page,
              page_size: 25,
            },
          })
          .then((r) => r.data),
    }),
    detail = useQuery({
      queryKey: ["report-host", host],
      queryFn: () => api.get(`/reports/hosts/${host}`).then((r) => r.data),
      enabled: !!host,
    }),
    scanDetail = useQuery({
      queryKey: ["report-scan", scan],
      queryFn: () => api.get(`/reports/scans/${scan}`).then((r) => r.data),
      enabled: !!scan,
    });
  if (host)
    return (
      <section>
        <button
          className="secondary"
          onClick={() => {
            setHost(undefined);
            setScan(undefined);
            onBack?.();
          }}
        >
          ← Reports
        </button>
        <h2>{detail.data?.hostname || "Loading host…"}</h2>
        {detail.isError ? (
          <p className="error">Unable to load host report.</p>
        ) : (
          <>
            <div className="cards">
              <Card title="Total scans" value={detail.data?.total_scans} />
              <Card
                title="Risk processes"
                value={detail.data?.risk_processes}
              />
              <Card title="Current status" value={detail.data?.status} />
            </div>
            <button onClick={() => download(`/reports/hosts/${host}/export`)}>
              Export this host
            </button>
            <table>
              <thead>
                <tr>
                  <th>Scan time</th>
                  <th>Status</th>
                  <th>Processes</th>
                  <th>Risk</th>
                  <th>User</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {detail.data?.history?.map((x: any) => (
                  <tr key={x.scan_id}>
                    <td>{time(x.scan_time)}</td>
                    <td>
                      <Badge status={x.status} />
                    </td>
                    <td>{x.processes}</td>
                    <td>{x.risk_processes}</td>
                    <td>{x.user}</td>
                    <td>
                      <button onClick={() => setScan(x.scan_id)}>View</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {scan && (
              <section className="progress">
                <h3>Scan details</h3>
                {scanDetail.isLoading ? (
                  <p>Loading scan result…</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Risk</th>
                        <th>PID</th>
                        <th>User</th>
                        <th>Process</th>
                        <th>Command</th>
                        <th>Cgroup</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scanDetail.data?.processes?.map((p: any, i: number) => (
                        <tr key={i}>
                          <td>
                            <Badge status={p.risk} />
                          </td>
                          <td>{p.pid}</td>
                          <td>{p.user}</td>
                          <td>{p.process_name}</td>
                          <td>{p.command_line}</td>
                          <td>{p.cgroup}</td>
                          <td>{p.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            )}
          </>
        )}
      </section>
    );
  return (
    <section>
      <header>
        <h1>Scan Report</h1>
        <button onClick={() => download("/reports/export")}>
          Export Excel
        </button>
      </header>
      {summary.isLoading ? (
        <p>Loading report…</p>
      ) : summary.isError ? (
        <p className="error">Unable to load report.</p>
      ) : (
        <div className="cards">
          {Object.entries(summary.data || {})
            .filter(([k]) => k !== "last_scan")
            .map(([k, v]) => (
              <Card key={k} title={k.replaceAll("_", " ")} value={String(v)} />
            ))}
        </div>
      )}
      <div className="toolbar">
        <input
          placeholder="Hostname, node name or IP"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={st}
          onChange={(e) => {
            setSt(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option>SAFE</option>
          <option>WARNING</option>
          <option>ERROR</option>
          <option>UNKNOWN</option>
        </select>
      </div>
      {hosts.isLoading ? (
        <p>Loading hosts…</p>
      ) : hosts.data?.items?.length ? (
        <>
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Hostname</th>
                <th>IP</th>
                <th>Last Scan</th>
                <th>Scans</th>
                <th>Processes</th>
                <th>Risk</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {hosts.data.items.map((x: any) => (
                <tr key={x.node_id}>
                  <td>
                    <Badge status={x.status} />
                  </td>
                  <td>{x.hostname}</td>
                  <td>{x.address}</td>
                  <td>{time(x.last_scan)}</td>
                  <td>{x.total_scans}</td>
                  <td>{x.processes_found}</td>
                  <td>{x.risk_processes}</td>
                  <td>
                    <button onClick={() => setHost(x.node_id)}>View</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <button
              className="secondary"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <span>Page {page}</span>
            <button
              className="secondary"
              disabled={page * 25 >= hosts.data.total}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        <p>No scanned hosts found for the selected filters.</p>
      )}
    </section>
  );
}
function JobDetail({ job, onClose }: { job: any; onClose: () => void }) {
  const scan = useQuery({
    queryKey: ["scan-job-detail", job.id],
    queryFn: () => api.get(`/scan/${job.id}`).then((r) => r.data),
    enabled: job.kind === "CGROUP SCAN",
    refetchInterval:
      job.kind === "CGROUP SCAN" &&
      ["PENDING", "QUEUED", "RUNNING"].includes(job.status)
        ? 2000
        : false,
  });
  const scanRows = useQuery({
    queryKey: ["scan-job-results", job.id],
    queryFn: () => api.get(`/scan/${job.id}/results`).then((r) => r.data),
    enabled: job.kind === "CGROUP SCAN",
    refetchInterval:
      job.kind === "CGROUP SCAN" &&
      ["PENDING", "QUEUED", "RUNNING"].includes(job.status)
        ? 2000
        : false,
  });
  const config = useQuery({
    queryKey: ["config-job-detail", job.id],
    queryFn: () =>
      api.get(`/service-config/jobs/${job.id}`).then((r) => r.data),
    enabled: job.kind !== "CGROUP SCAN",
    refetchInterval:
      job.kind !== "CGROUP SCAN" && ["QUEUED", "RUNNING"].includes(job.status)
        ? 2000
        : false,
  });
  const info = job.kind === "CGROUP SCAN" ? scan.data : config.data;
  const nodes =
    job.kind === "CGROUP SCAN"
      ? (scanRows.data || []).map((x: any) => ({
          node_id: x.node_id,
          hostname: x.hostname,
          status: x.status,
          detail: x.error_message || x.risk || x.command_line || "Completed",
        }))
      : config.data?.nodes || [];
  return (
    <section className="progress">
      <header>
        <h2>Job detail</h2>
        <button className="secondary" onClick={onClose}>
          Close
        </button>
      </header>
      <p>
        <strong>Job Name:</strong> {job.jobName || info?.job_name || "—"} &nbsp;{" "}
        <strong>Type:</strong> {job.kind} &nbsp; <strong>ID:</strong> {job.id}{" "}
        &nbsp; <strong>Created:</strong>{" "}
        {time(info?.created_at || job.created_at)} &nbsp;{" "}
        <strong>Started:</strong> {time(info?.started_at || job.started)} &nbsp;{" "}
        <strong>Finished:</strong> {time(info?.finished_at)}
      </p>
      <p>
        <Badge status={info?.status || job.status} />{" "}
        <progress
          value={info?.progress_percent ?? job.progress_percent ?? 0}
          max="100"
        />{" "}
        {info?.progress_percent ?? job.progress_percent ?? 0}% —{" "}
        {info?.completed ?? job.completed}/{info?.total ?? job.total} completed
      </p>
      <table>
        <thead>
          <tr>
            <th>Node</th>
            <th>Node Name</th>
            <th>IP</th>
            <th>Status</th>
            <th>Information</th>
          </tr>
        </thead>
        <tbody>
          {nodes.length ? (
            nodes.map((node: any, index: number) => (
              <tr key={node.node_id || index}>
                <td>{node.node_id || "—"}</td>
                <td>{node.node_name || node.hostname || "—"}</td>
                <td>{node.address || "—"}</td>
                <td>
                  <Badge status={node.status || "UNKNOWN"} />
                </td>
                <td>
                  {node.detail ||
                    node.error_message ||
                    node.restart_status ||
                    node.kill_mode ||
                    "Running / queued"}
                </td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={6}>
                No node has completed yet. This panel refreshes while the job is
                running.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
function Jobs() {
  const [detail, setDetail] = useState<any>();
  const scans = useQuery({
      queryKey: ["scan-jobs"],
      queryFn: () => api.get("/history").then((r) => r.data),
      refetchInterval: 2000,
    }),
    configs = useQuery({
      queryKey: ["service-config-jobs"],
      queryFn: () => api.get("/service-config/history").then((r) => r.data),
      refetchInterval: 2000,
    }),
    discoveries = useQuery({
      queryKey: ["compute-discovery-jobs"],
      queryFn: () => api.get("/compute-discovery/jobs").then((r) => r.data.items),
      refetchInterval: (q) => (q.state.data || []).some((x: any) => ["QUEUED", "RUNNING"].includes(x.status)) ? 2000 : false,
    });
  const cancel = async (id: string) => {
    await api.post(`/scan/${id}/cancel`);
    await scans.refetch();
  };
  const retryFailed = async (job: any) => {
    const path = job.kind === "CGROUP SCAN" ? `/scan/${job.id}/retry-failed` : `/compute-discovery/jobs/${job.id}/retry-failed`;
    await api.post(path);
    await Promise.all([scans.refetch(), discoveries.refetch()]);
  };
  const all = [
    ...(scans.data || []).map((x: any) => ({
      ...x,
      kind: "CGROUP SCAN",
      started: x.start_time,
      total: x.total_nodes,
      completed: x.completed_nodes,
      success: x.safe_nodes + x.warning_nodes,
      error: x.error_nodes + x.unreachable_nodes,
    })),
    ...(configs.data || []).map((x: any) => ({
      ...x,
      id: x.job_id,
      kind: `SERVICE ${x.operation}`,
      started: x.created_at,
      total: x.total,
      completed: x.completed,
      success: x.success,
      error: x.error,
    })),
    ...(discoveries.data || []).map((x: any) => ({
      ...x, id: x.job_id, kind: "COMPUTE DISCOVERY", started: x.started_at || x.created_at,
      jobName: x.job_name, total: x.total_nodes, completed: x.completed_nodes,
      success: x.success_nodes, error: x.failed_nodes,
    })),
  ].sort((a: any, b: any) =>
    String(b.started).localeCompare(String(a.started)),
  );
  return (
    <section>
      <header>
        <h1>Jobs</h1>
        <button
          className="secondary"
          onClick={() => {
            scans.refetch();
            configs.refetch();
            discoveries.refetch();
          }}
        >
          Tải lại
        </button>
      </header>
      <p className="notice">
        Cgroup Scan và Service Config tiếp tục chạy trên backend khi đổi trang.
        Chọn Xem để theo dõi từng node trong job.
      </p>
      {detail && (detail.kind === "COMPUTE DISCOVERY" ? <DiscoveryJobDetail job={detail} onClose={() => setDetail(undefined)} /> : <JobDetail job={detail} onClose={() => setDetail(undefined)} />)}
      {!all.length ? (
        <p>No running or historical jobs yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Started</th>
              <th>Job ID</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Completed</th>
              <th>Success</th>
              <th>Error</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {all.map((job: any) => (
              <tr key={job.kind + job.id}>
                <td>{job.kind}</td>
                <td>{time(job.started)}</td>
                <td>{job.id}</td>
                <td>
                  <Badge status={job.status} />
                </td>
                <td>
                  <progress value={job.progress_percent || 0} max="100" />{" "}
                  {job.progress_percent || 0}%
                </td>
                <td>
                  {job.completed}/{job.total}
                </td>
                <td>{job.success}</td>
                <td>{job.error}</td>
                <td>
                  <button className="secondary" onClick={() => setDetail(job)}>
                    Xem
                  </button>
                  {job.kind === "CGROUP SCAN" && (
                    <button
                      className="secondary"
                      disabled={
                        !["PENDING", "QUEUED", "RUNNING"].includes(job.status)
                      }
                      onClick={() => cancel(job.id)}
                    >
                      Stop
                    </button>
                  )}
                  {(["CGROUP SCAN", "COMPUTE DISCOVERY"].includes(job.kind) && Number(job.error || 0) > 0) && (
                    <button className="secondary" onClick={() => retryFailed(job)}>Thử lại node lỗi</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
function Criteria() {
  return (
    <section>
      <header>
        <h1>Nguyên tắc scan</h1>
      </header>
      <div className="progress">
        <h3>Phạm vi kiểm tra</h3>
        <p>
          Tool chỉ đọc process thuộc cgroup thực tế của{" "}
          <code>teleport.service</code>. Cgroup được lấy động bằng{" "}
          <code>systemctl show teleport.service -p ControlGroup --value</code>,
          không hard-code đường dẫn.
        </p>
        <h3>Dữ liệu được đọc</h3>
        <p>
          <code>cgroup.procs</code>, <code>ps</code>,{" "}
          <code>/proc/&lt;PID&gt;/exe</code> và{" "}
          <code>/proc/&lt;PID&gt;/cmdline</code>. Các lệnh đều read-only; tool
          không restart service, kill process hoặc thay đổi node.
        </p>
        <h3>Phân loại kết quả</h3>
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Điều kiện</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <Badge status="SAFE" />
              </td>
              <td>
                Không còn process nào ngoài danh sách được loại trừ trong
                teleport.service cgroup.
              </td>
            </tr>
            <tr>
              <td>
                <Badge status="WARNING" />
              </td>
              <td>
                Có process khác Teleport trong cgroup; process này có thể bị
                terminate khi restart teleport.service.
              </td>
            </tr>
            <tr>
              <td>
                <Badge status="ERROR" />
              </td>
              <td>
                SSH được nhưng không tìm thấy/không đọc được service hoặc
                cgroup.
              </td>
            </tr>
            <tr>
              <td>
                <Badge status="UNREACHABLE" />
              </td>
              <td>Không SSH được qua Teleport hoặc timeout.</td>
            </tr>
          </tbody>
        </table>
        <h3>Process được loại trừ</h3>
        <p>
          Chỉ match chính xác executable hoặc command đầu tiên:{" "}
          <code>/usr/local/bin/teleport</code>, <code>teleport</code>,{" "}
          <code>bash</code>, <code>/bin/bash</code>, <code>/usr/bin/bash</code>.
        </p>
        <p>
          <strong>Lưu ý:</strong> <code>java</code>, <code>python</code>,{" "}
          <code>node</code>, <code>nginx</code>, <code>postgres</code>,{" "}
          <code>sh</code> và script ứng dụng trong cgroup sẽ là{" "}
          <Badge status="WARNING" /> để người vận hành xác minh.
        </p>
      </div>
    </section>
  );
}
function ServiceConfig({ role }: { role: AppRole }) {
  const [q, setQ] = useState(""),
    [term, setTerm] = useState(""),
    [page, setPage] = useState(1),
    [selected, setSelected] = useState<Set<number>>(new Set()),
    [restart, setRestart] = useState(false),
    [notice, setNotice] = useState(""),
    [confirmation, setConfirmation] = useState<number[] | null>(null),
    [jobName, setJobName] = useState(""),
    [typedConfirmation, setTypedConfirmation] = useState(""),
    [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(q);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [q]);
  const data = useQuery({
    queryKey: ["service-config", term, page],
    queryFn: () =>
      api
        .get("/service-config/nodes", {
          params: { search: term, page, page_size: 50 },
        })
        .then((r) => r.data),
  });
  const run = async (
    operation: "check" | "configure" | "rollback",
    ids: number[],
  ) => {
    const clean = [...new Set(ids)];
    if (!clean.length) {
      setNotice("Select at least one node first.");
      return;
    }
    setNotice("");
    if (operation === "configure") {
      if (role !== "ADMIN") { setNotice("Only Admin can apply service configuration."); return; }
      setConfirmation(clean);
      return;
    }
    const job_name = "";
    try {
      const r = await api.post("/service-config/" + operation, {
        node_ids: clean,
        job_name,
        method: "override",
        restart_after_apply: false,
      });
      setNotice(
        `Job ${r.data.job_id} queued. You can create another job after selecting nodes again.`,
      );
      setSelected(new Set());
      setTimeout(() => data.refetch(), 1000);
    } catch (e: any) {
      setNotice(e.response?.data?.detail || "Unable to create job.");
      setSelected(new Set());
    }
  };
  const submitConfiguration = async () => {
    const ids = confirmation || [];
    if (typedConfirmation !== "APPLY CONFIGURATION") return;
    setSubmitting(true); setNotice("");
    try {
      const r = await api.post("/service-config/configure", { node_ids: ids, job_name: jobName || undefined, method: "override", restart_after_apply: restart });
      setNotice(`Configuration job ${r.data.job_id} queued. Track progress in Jobs.`);
      setSelected(new Set()); setRestart(false); setConfirmation(null); setJobName(""); setTypedConfirmation("");
      setTimeout(() => data.refetch(), 1000);
    } catch (e: any) { setNotice(e.response?.data?.detail || "Unable to create configuration job."); }
    finally { setSubmitting(false); }
  };
  const rows = data.data?.items || [],
    all = rows.length > 0 && rows.every((n: any) => selected.has(n.id)),
    toggle = (id: number) =>
      setSelected((x) => {
        const y = new Set(x);
        y.has(id) ? y.delete(id) : y.add(id);
        return y;
      });
  return (
    <section>
      <header>
        <h1>Cấu hình dịch vụ</h1>
        <button onClick={() => data.refetch()}>Tải lại trạng thái</button>
      </header>
      <div className="cards">
        <Card title="Tổng số node" value={data.data?.total} />
        <Card
          title="Đã kiểm tra"
          value={rows.filter((x: any) => x.config_status !== "UNKNOWN").length}
        />
        <Card
          title="Đã cấu hình"
          value={
            rows.filter(
              (x: any) =>
                x.config_status === "CONFIGURED" ||
                x.config_status === "SUCCESS",
            ).length
          }
        />
        <Card
          title="Cần cấu hình"
          value={
            rows.filter((x: any) => x.config_status === "NOT_CONFIGURED").length
          }
        />
      </div>
      <input
        className="node-search"
        aria-label="Tìm node cấu hình dịch vụ"
        placeholder="Tìm tên node, hostname, IP hoặc nhãn…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="selection-bar">
        <span>Đã chọn {selected.size} node</span>
        <button
          disabled={!selected.size || role === "VIEWER"}
          onClick={() => run("check", [...selected])}
        >
          Kiểm tra đã chọn
        </button>
        <button
          disabled={!selected.size || role !== "ADMIN"}
          title={role !== "ADMIN" ? "Chỉ Admin có thể áp dụng cấu hình" : undefined}
          onClick={() => run("configure", [...selected])}
        >
          Cấu hình đã chọn
        </button>
        <label>
          <input
            type="checkbox"
            checked={restart}
            onChange={(e) => setRestart(e.target.checked)}
          />{" "}
          Khởi động lại sau khi áp dụng
        </label>
        <button className="secondary" onClick={() => setSelected(new Set())}>
          Bỏ chọn
        </button>
      </div>
      {notice && <p className="notice">{notice}</p>}
      {confirmation && <Dialog title="Xác nhận cấu hình dịch vụ" onClose={() => { if (!submitting) { setConfirmation(null); setJobName(""); setTypedConfirmation(""); } }}><p><strong>Node ảnh hưởng:</strong> {confirmation.length}</p><p><strong>Đích áp dụng:</strong> KillMode=process (systemd override)</p><p><strong>Yêu cầu khởi động lại:</strong> {restart ? "Có — kết nối Teleport có thể bị gián đoạn." : "Không"}</p><p className="notice">Thao tác này thay đổi cấu hình dịch vụ từ xa. Hãy xem lại tác động trước khi tiếp tục.</p><label>Tên job (không bắt buộc)<input autoFocus maxLength={150} value={jobName} onChange={(e) => setJobName(e.target.value)} /></label><label>Nhập <code>APPLY CONFIGURATION</code> để xác nhận<input value={typedConfirmation} onChange={(e) => setTypedConfirmation(e.target.value)} /></label><div className="dialog-actions"><button className="secondary" disabled={submitting} onClick={() => { setConfirmation(null); setJobName(""); setTypedConfirmation(""); }}>Hủy</button><button disabled={submitting || typedConfirmation !== "APPLY CONFIGURATION"} onClick={submitConfiguration}>{submitting ? "Đang áp dụng…" : restart ? "Áp dụng & khởi động lại Teleport" : "Áp dụng cấu hình"}</button></div></Dialog>}
      {data.isLoading ? (
        <p>Đang tải cấu hình…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={all}
                  onChange={() =>
                    setSelected((x) => {
                      const y = new Set(x);
                      rows.forEach((n: any) =>
                        all ? y.delete(n.id) : y.add(n.id),
                      );
                      return y;
                    })
                  }
                />
              </th>
              <th>Hostname</th>
              <th>IP</th>
              <th>Labels</th>
              <th>KillMode</th>
              <th>Config Status</th>
              <th>Service</th>
              <th>Last Check</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n: any) => (
              <tr key={n.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(n.id)}
                    onChange={() => toggle(n.id)}
                  />
                </td>
                <td>{n.hostname}</td>
                <td>{n.address}</td>
                <td>
                  <Labels labels={n.labels} />
                </td>
                <td>{n.kill_mode || "UNKNOWN"}</td>
                <td>
                  <Badge status={n.config_status} />
                </td>
                <td>{n.service_state || "—"}</td>
                <td>{time(n.last_check)}</td>
                <td>
                  <button onClick={() => run("check", [n.id])}>Kiểm tra</button>{" "}
                  <button
                    disabled={n.config_status === "CONFIGURED"}
                    onClick={() => run("configure", [n.id])}
                  >
                    Cấu hình
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="pagination">
        <button
          className="secondary"
          disabled={page === 1}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </button>
        <span>Page {page}</span>
        <button
          className="secondary"
          disabled={page * 50 >= (data.data?.total || 0)}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
    </section>
  );
}
function ReportUI({
  initialHost,
  onBack,
}: {
  initialHost?: number;
  onBack?: () => void;
}) {
  const [q, setQ] = useState(""),
    [st, setSt] = useState(""),
    [page, setPage] = useState(1),
    [host, setHost] = useState<number | undefined>(initialHost),
    [selected, setSelected] = useState<Set<number>>(new Set()),
    [confirm, setConfirm] = useState<number[] | null>(null);
  useEffect(() => setHost(initialHost), [initialHost]);
  const summary = useQuery({
      queryKey: ["report-summary"],
      queryFn: () => api.get("/reports/summary").then((r) => r.data),
    }),
    hosts = useQuery({
      queryKey: ["report-hosts", q, st, page],
      queryFn: () =>
        api
          .get("/reports/hosts", {
            params: {
              search: q || undefined,
              status: st || undefined,
              page,
              page_size: 25,
            },
          })
          .then((r) => r.data),
    });
  const refresh = () => {
    summary.refetch();
    hosts.refetch();
  };
  const remove = async () => {
    if (!confirm) return;
    try {
      const r =
        confirm.length === 1
          ? await api.delete(`/reports/nodes/${confirm[0]}`)
          : await api.post("/reports/remove", { node_ids: confirm });
      const failed = (r.data.results || []).filter(
        (x: any) => x.status !== "REMOVED",
      );
      if (failed.length)
        alert(`${failed.length} node(s) could not be removed.`);
      setSelected((x) => {
        const y = new Set(x);
        confirm.forEach((id) => y.delete(id));
        return y;
      });
      setConfirm(null);
      refresh();
    } catch (e: any) {
      alert(e.response?.data?.detail || "Unable to remove report data.");
    }
  };
  if (host) return <Report initialHost={host} onBack={onBack} />;
  const rows = hosts.data?.items || [],
    all = rows.length > 0 && rows.every((x: any) => selected.has(x.node_id)),
    some = rows.some((x: any) => selected.has(x.node_id));
  return (
    <section>
      <header>
        <h1>Scan Report</h1>
        <button onClick={() => download("/reports/export")}>
          Export Excel
        </button>
      </header>
      {summary.isLoading ? (
        <p>Loading report…</p>
      ) : (
        <div className="cards">
          {Object.entries(summary.data || {})
            .filter(([k]) => k !== "last_scan")
            .map(([k, v]) => (
              <Card key={k} title={k.replaceAll("_", " ")} value={String(v)} />
            ))}
        </div>
      )}
      <div className="toolbar">
        <input
          placeholder="Hostname, node name or IP"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={st}
          onChange={(e) => {
            setSt(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option>SAFE</option>
          <option>WARNING</option>
          <option>ERROR</option>
          <option>UNKNOWN</option>
        </select>
      </div>
      <div className="selection-bar">
        <span>{selected.size} nodes selected</span>
        <button
          disabled={!selected.size}
          onClick={() =>
            download(
              `/reports/export?${[...selected].map((id) => `node_ids=${id}`).join("&")}`,
            )
          }
        >
          Export Selected
        </button>
        <button
          disabled={!selected.size}
          onClick={() => setConfirm([...selected])}
        >
          Remove Selected
        </button>
        <button className="secondary" onClick={() => setSelected(new Set())}>
          Clear Selection
        </button>
      </div>
      {hosts.isLoading ? (
        <p>Loading hosts…</p>
      ) : rows.length ? (
        <>
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    checked={all}
                    ref={(e) => {
                      if (e) e.indeterminate = !all && some;
                    }}
                    onChange={() =>
                      setSelected((x) => {
                        const y = new Set(x);
                        rows.forEach((n: any) =>
                          all ? y.delete(n.node_id) : y.add(n.node_id),
                        );
                        return y;
                      })
                    }
                  />
                </th>
                <th>Status</th>
                <th>Hostname</th>
                <th>IP</th>
                <th>Last Scan</th>
                <th>Scans</th>
                <th>Processes</th>
                <th>Risk</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x: any) => (
                <tr key={x.node_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(x.node_id)}
                      onChange={() =>
                        setSelected((y) => {
                          const z = new Set(y);
                          z.has(x.node_id)
                            ? z.delete(x.node_id)
                            : z.add(x.node_id);
                          return z;
                        })
                      }
                    />
                  </td>
                  <td>
                    <Badge status={x.status} />
                  </td>
                  <td>{x.hostname}</td>
                  <td>{x.address || "—"}</td>
                  <td>{time(x.last_scan)}</td>
                  <td>{x.total_scans}</td>
                  <td>{x.processes_found}</td>
                  <td>{x.risk_processes}</td>
                  <td>
                    <button onClick={() => setHost(x.node_id)}>View</button>{" "}
                    <button
                      className="secondary"
                      onClick={() => setConfirm([x.node_id])}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <button
              className="secondary"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <span>Page {page}</span>
            <button
              className="secondary"
              disabled={page * 25 >= hosts.data.total}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        <p>No scanned hosts found for the selected filters.</p>
      )}
      {confirm && (
        <Dialog title={`Xóa ${confirm.length} node khỏi báo cáo?`} onClose={() => setConfirm(null)}>
            <p>
              Chỉ xóa dữ liệu báo cáo/lịch sử của ứng dụng. Node và agent
              Teleport không bị thay đổi hoặc khởi động lại.
            </p>
            <button className="secondary" onClick={() => setConfirm(null)}>
              Hủy
            </button>{" "}
            <button onClick={remove}>Xóa báo cáo</button>
        </Dialog>
      )}
    </section>
  );
}
function DiscoveryJobDetail({ job, onClose }: { job: any; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["compute-discovery-job", job.id],
    queryFn: () => api.get(`/compute-discovery/jobs/${job.id}`).then((r) => r.data),
    refetchInterval: (q) => ["QUEUED", "RUNNING"].includes(q.state.data?.status || job.status) ? 2000 : false,
  });
  const value = query.data || job;
  return <section className="progress"><header><h2>Compute Discovery job detail</h2><button className="secondary" onClick={onClose}>Close</button></header>
    <p><strong>Job Name:</strong> {value.job_name} &nbsp; <strong>Type:</strong> COMPUTE DISCOVERY &nbsp; <strong>ID:</strong> {value.job_id || value.id}</p>
    <p><Badge status={value.status} /> <progress value={value.progress_percent || 0} max="100" /> {value.completed_nodes || value.completed || 0}/{value.total_nodes || value.total || 0} completed; success {value.success_nodes || value.success || 0}; error {value.failed_nodes || value.error || 0}</p>
    <table><thead><tr><th>Node Name</th><th>IP</th><th>Compute</th><th>NIC</th><th>Result</th><th>Scanned At</th><th>Error / LLDP detail</th></tr></thead><tbody>{(value.nodes || []).length ? value.nodes.map((node: any) => <tr key={node.node_id + String(node.discovered_at)}><td>{node.hostname}</td><td>{node.address || "—"}</td><td>{node.compute || "—"}</td><td>{node.nic || "—"}</td><td><Badge status={node.status} /></td><td>{time(node.discovered_at)}</td><td>{node.detail || "—"}</td></tr>) : <tr><td colSpan={7}>No node has completed yet. This panel refreshes while the job is running.</td></tr>}</tbody></table>
  </section>;
}
function JobsUI() {
  const [detail, setDetail] = useState<any>();
  const scans = useQuery({
      queryKey: ["scan-jobs"],
      queryFn: () => api.get("/history").then((r) => r.data),
      refetchInterval: 2000,
    }),
    configs = useQuery({
      queryKey: ["service-config-jobs"],
      queryFn: () => api.get("/service-config/history").then((r) => r.data),
      refetchInterval: 2000,
    });
  const all = [
    ...(scans.data || []).map((x: any) => ({
      ...x,
      kind: "CGROUP SCAN",
      started: x.start_time,
      jobName: x.job_name || `Cgroup Scan - ${time(x.start_time)}`,
      total: x.total_nodes,
      completed: x.completed_nodes,
      success: x.safe_nodes + x.warning_nodes,
      error: x.error_nodes + x.unreachable_nodes,
    })),
    ...(configs.data || []).map((x: any) => ({
      ...x,
      id: x.job_id,
      kind: `SERVICE ${x.operation}`,
      started: x.started_at || x.created_at,
      jobName:
        x.job_name ||
        `${x.operation === "CHECK" ? "Service Check" : "Service Configure"} - ${time(x.created_at)}`,
      total: x.total,
      completed: x.completed,
      success: x.success,
      error: x.error,
    })),
  ].sort((a: any, b: any) =>
    String(b.started).localeCompare(String(a.started)),
  );
  return (
    <section>
      <header>
        <h1>Running Job</h1>
        <button
          className="secondary"
          onClick={() => {
            scans.refetch();
            configs.refetch();
          }}
        >
          Refresh
        </button>
      </header>
      {detail && (
        <JobDetail job={detail} onClose={() => setDetail(undefined)} />
      )}{" "}
      {!all.length ? (
        <p>No jobs yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Job Name</th>
              <th>Type</th>
              <th>Started</th>
              <th>Job ID</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Completed</th>
              <th>Success</th>
              <th>Error</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {all.map((job: any) => (
              <tr key={job.kind + job.id}>
                <td>{job.jobName}</td>
                <td>{job.kind}</td>
                <td>{time(job.started)}</td>
                <td>{job.id}</td>
                <td>
                  <Badge status={job.status} />
                </td>
                <td><progress value={job.progress_percent || 0} max="100" /> {job.progress_percent || 0}%</td>
                <td>
                  {job.completed}/{job.total}
                </td>
                <td>{job.success}</td>
                <td>{job.error}</td>
                <td>
                  <button className="secondary" onClick={() => setDetail(job)}>
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
function ConfigReport() {
  const [q, setQ] = useState(""),
    [status, setStatus] = useState(""),
    [page, setPage] = useState(1),
    [selected, setSelected] = useState<Set<number>>(new Set()),
    [detail, setDetail] = useState<any>();
  const summary = useQuery({
      queryKey: ["config-report-summary"],
      queryFn: () => api.get("/config-report/summary").then((r) => r.data),
    }),
    data = useQuery({
      queryKey: ["config-report-nodes", q, status, page],
      queryFn: () =>
        api
          .get("/config-report/nodes", {
            params: { search: q, status, page, page_size: 50 },
          })
          .then((r) => r.data),
    }),
    d = useQuery({
      queryKey: ["config-report-detail", detail],
      queryFn: () =>
        api.get(`/config-report/nodes/${detail}`).then((r) => r.data),
      enabled: !!detail,
    });
  const rows = data.data?.items || [],
    all = rows.length > 0 && rows.every((x: any) => selected.has(x.node_id));
  const exportReport = async () => {
    const r = await api.post(
      "/config-report/export",
      selected.size ? { node_ids: [...selected] } : { search: q, status },
      { responseType: "blob" },
    );
    const u = URL.createObjectURL(r.data),
      a = document.createElement("a");
    a.href = u;
    a.download = "Teleport_Config_Report.xlsx";
    a.click();
    URL.revokeObjectURL(u);
  };
  if (detail)
    return (
      <section>
        <button className="secondary" onClick={() => setDetail(undefined)}>
          ← Config Report
        </button>
        <h2>{d.data?.node?.node_name || "Loading…"}</h2>
        {d.data && (
          <>
            <p>
              IP: {d.data.node.ip || "—"} | KillMode:{" "}
              {d.data.node.kill_mode || "—"} | Status:{" "}
              {d.data.node.config_status}
            </p>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Job Name</th>
                  <th>Operation</th>
                  <th>Previous</th>
                  <th>New</th>
                  <th>Restart</th>
                  <th>Service</th>
                  <th>Status</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {d.data.history.map((x: any) => (
                  <tr>
                    <td>{time(x.finished_at)}</td>
                    <td>{x.job_name}</td>
                    <td>{x.operation}</td>
                    <td>{x.previous_kill_mode || "—"}</td>
                    <td>{x.new_kill_mode || "—"}</td>
                    <td>{x.restart_status}</td>
                    <td>{x.service_state_after || "—"}</td>
                    <td>
                      <Badge status={x.status} />
                    </td>
                    <td>{x.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    );
  return (
    <section>
      <header>
        <h1>Config Report</h1>
        <button onClick={exportReport}>
          Export {selected.size ? "Selected" : "Current Filter"}
        </button>
      </header>
      <div className="cards">
        {Object.entries(summary.data || {}).map(([k, v]) => (
          <Card key={k} title={k.replaceAll("_", " ")} value={String(v)} />
        ))}
      </div>
      <div className="toolbar">
        <input
          placeholder="Search node, IP, label or job name"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option>CONFIGURED</option>
          <option>NOT_CONFIGURED</option>
          <option>ERROR</option>
        </select>
      </div>
      <div className="selection-bar">
        <span>{selected.size} nodes selected</span>
        <button className="secondary" onClick={() => setSelected(new Set())}>
          Clear Selection
        </button>
      </div>
      {rows.length ? (
        <>
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    checked={all}
                    onChange={() =>
                      setSelected((x) => {
                        const y = new Set(x);
                        rows.forEach((n: any) =>
                          all ? y.delete(n.node_id) : y.add(n.node_id),
                        );
                        return y;
                      })
                    }
                  />
                </th>
                <th>Node Name</th>
                <th>IP</th>
                <th>KillMode</th>
                <th>Status</th>
                <th>Operation</th>
                <th>Job Name</th>
                <th>Restart</th>
                <th>Service</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x: any) => (
                <tr>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(x.node_id)}
                      onChange={() =>
                        setSelected((y) => {
                          const z = new Set(y);
                          z.has(x.node_id)
                            ? z.delete(x.node_id)
                            : z.add(x.node_id);
                          return z;
                        })
                      }
                    />
                  </td>
                  <td>{x.node_name}</td>
                  <td>{x.ip || "—"}</td>
                  <td>{x.kill_mode || "—"}</td>
                  <td>
                    <Badge status={x.config_status} />
                  </td>
                  <td>{x.last_operation}</td>
                  <td>{x.job_name}</td>
                  <td>{x.restart_status}</td>
                  <td>{x.service_state}</td>
                  <td>
                    <button onClick={() => setDetail(x.node_id)}>View</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <button
              className="secondary"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <span>Page {page}</span>
            <button
              className="secondary"
              disabled={page * 50 >= data.data.total}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        <p>
          No configuration report data found. Run Service Check or Service
          Configure first.
        </p>
      )}
    </section>
  );
}
function ComputeDiscovery({ role }: { role: AppRole }) {
  const [page, setPage] = useState(1), [pageSize,setPageSize] = useState(25), [search,setSearch]=useState(""), [term,setTerm]=useState(""), [discoveryStatus,setDiscoveryStatus]=useState(""), [saveDialog,setSaveDialog]=useState(false), [viewName,setViewName]=useState(""), [scheduleDialog,setScheduleDialog]=useState(false), [scheduleName,setScheduleName]=useState(""), [scheduleMinutes,setScheduleMinutes]=useState("60");
  useEffect(()=>{const timer=window.setTimeout(()=>{setTerm(search);setPage(1)},400);return()=>clearTimeout(timer)},[search]);
  const nodes = useQuery({
      queryKey: ["compute-nodes", page, term, discoveryStatus],
      queryFn: () =>
        api
          .get("/nodes", { params: { page, page_size: pageSize, search:term||undefined, discovery_status:discoveryStatus||undefined } })
          .then((r) => r.data),
    }),
    savedViews = useQuery({ queryKey:["saved-views","compute-discovery"], queryFn:()=>api.get("/saved-views",{params:{page:"compute-discovery"}}).then(r=>r.data.items) }),
    schedules = useQuery({ queryKey:["compute-schedules"], queryFn:()=>api.get("/scheduled-checks").then(r=>r.data.items) }),
    alerts = useQuery({ queryKey:["scheduled-alerts"], queryFn:()=>api.get("/scheduled-checks/alerts").then(r=>r.data.items), refetchInterval:30000 }),
    [selected, setSelected] = useState<Set<number>>(new Set()), [notice, setNotice] = useState(""), [creationError, setCreationError] = useState(""),
    [dialog, setDialog] = useState(false), [jobName, setJobName] = useState(""), [submitting, setSubmitting] = useState(false), [activeJob, setActiveJob] = useState<any>();
  const hosts: Node[] = nodes.data?.items || [],
    all = hosts.length > 0 && hosts.every((x) => selected.has(x.id)),
    pages = Math.max(1, Math.ceil((nodes.data?.total || 0) / pageSize)),
    toggle = (id: number) =>
      setSelected((x) => {
        const y = new Set(x);
        y.has(id) ? y.delete(id) : y.add(id);
        return y;
      });
  const togglePage = () =>
    setSelected((x) => {
      const y = new Set(x);
      hosts.forEach((n) => (all ? y.delete(n.id) : y.add(n.id)));
      return y;
    });
  const run = async () => {
    const ids = [...selected];
    if (!ids.length) return setCreationError("Hãy chọn ít nhất một node.");
    if (ids.length > 1800) return setCreationError(`Không thể tạo job: đã chọn ${ids.length} node, giới hạn là 1.800 node mỗi job.`);
    setCreationError("");
    setSubmitting(true);
    try {
      const r = await api.post("/compute-discovery/jobs", { node_ids: ids, job_name: jobName || undefined });
      setActiveJob(r.data); setNotice(`Discovery job ${r.data.job_id} queued. Track progress in Running Job.`); setSelected(new Set()); setJobName(""); setDialog(false);
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const message = detail?.message || (Array.isArray(detail) ? detail.map((item:any) => item.msg).filter(Boolean).join(". ") : detail);
      setCreationError(message || "Không thể tạo Compute Discovery job. Vui lòng thử lại hoặc kiểm tra quyền truy cập.");
    } finally {
      setSubmitting(false);
    }
  };
  const saveView = async () => { if (!viewName.trim()) return; await api.post("/saved-views",{page:"compute-discovery",name:viewName.trim(),filters:{search,discoveryStatus,pageSize}}); setViewName(""); setSaveDialog(false); savedViews.refetch(); };
  const applyView = (id:string) => { const view=(savedViews.data||[]).find((x:any)=>String(x.id)===id); if(!view)return; const filters=view.filters||{}; setSearch(filters.search||""); setTerm(filters.search||""); setDiscoveryStatus(filters.discoveryStatus||""); setPageSize([25,50,100,500].includes(Number(filters.pageSize))?Number(filters.pageSize):25); setPage(1); };
  const createSchedule = async () => { const interval=Number(scheduleMinutes); if (!scheduleName.trim() || !selected.size || ![5,15,30,60,240,1440].includes(interval)) return; await api.post("/scheduled-checks",{name:scheduleName.trim(),operation:"COMPUTE_DISCOVERY",node_ids:[...selected],interval_minutes:interval}); setScheduleDialog(false); setScheduleName(""); schedules.refetch(); };
  const job = useQuery({ queryKey: ["compute-active-job", activeJob?.job_id], queryFn: () => api.get(`/compute-discovery/jobs/${activeJob.job_id}`).then(r => r.data), enabled: !!activeJob?.job_id, refetchInterval: (q) => ["QUEUED", "RUNNING"].includes(q.state.data?.status || activeJob?.status) ? 2500 : false });
  return (
    <section>
      <header>
        <h1>Compute Discovery</h1>
        <div className="dialog-actions"><button disabled={!selected.size || role === "VIEWER"} title={role === "VIEWER" ? "Viewer chỉ có quyền xem" : undefined} onClick={() => { setCreationError(""); setDialog(true); }}>{`Quét đã chọn (${selected.size})`}</button><button className="secondary" disabled={!selected.size || role === "VIEWER"} onClick={() => setScheduleDialog(true)}>Lập lịch</button></div>
      </header>
      <p className="notice">
        Chọn node trước. Discovery chỉ đọc và thu thập LLDP tối đa 60 giây cho
        mỗi host.
      </p>
      {notice && <p className="notice">{notice}</p>}
      {activeJob && <div className="progress"><strong>{job.data?.job_name || activeJob.job_name || "Compute Discovery"}</strong> <Badge status={job.data?.status || activeJob.status} /> <progress value={job.data?.progress_percent || 0} max="100" /> {job.data?.completed_nodes || 0}/{job.data?.total_nodes || activeJob.total_nodes} completed</div>}
      <div className="selection-bar">
        <span>Đã chọn {selected.size} node</span>
        <button className="secondary" onClick={() => setSelected(new Set())}>
          Bỏ chọn
        </button>
      </div>
      <div className="toolbar"><input aria-label="Tìm node discovery" placeholder="Tìm node, IP, nhãn, system hoặc compute…" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="Lọc trạng thái discovery" value={discoveryStatus} onChange={e=>{setDiscoveryStatus(e.target.value);setPage(1)}}><option value="">Tất cả trạng thái discovery</option><option>DETECTED</option><option>NOT_DETECTED</option><option>UNREACHABLE</option><option>ERROR</option><option>NOT_SCANNED</option></select><select aria-label="Số dòng mỗi trang" value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1)}}>{[25,50,100,500].map(value=><option key={value} value={value}>{value} dòng/trang</option>)}</select><select aria-label="Saved view" defaultValue="" onChange={e=>applyView(e.target.value)}><option value="">Saved views…</option>{(savedViews.data||[]).map((view:any)=><option key={view.id} value={view.id}>{view.name}</option>)}</select><button className="secondary" onClick={()=>setSaveDialog(true)}>Lưu view</button></div>
      {nodes.isLoading ? (
        <p>Đang tải node…</p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>
                  <input type="checkbox" checked={all} onChange={togglePage} />
                </th>
                <th>Node Name</th>
                <th>IP</th>
                <th>System</th>
                <th>Labels</th>
                <th>Latest Compute</th><th>Discovery Status</th><th>Reason</th><th>Last Discovery</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((x) => (
                <tr key={x.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(x.id)}
                      onChange={() => toggle(x.id)}
                    />
                  </td>
                  <td>{x.hostname}</td>
                  <td>{x.address || "—"}</td>
                  <td>{(x.labels as any)?.system || "—"}</td>
                  <td>
                    <Labels labels={x.labels} />
                  </td>
                  <td>{(x as any).latest_compute || "—"}</td><td>{(x as any).discovery_status ? <Badge status={(x as any).discovery_status}/>:"NOT_SCANNED"}</td><td>{(x as any).discovery_reason_code || "—"}</td><td>{time((x as any).last_discovery)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <span>
              Showing {nodes.data?.total ? (page - 1) * pageSize + 1 : 0}–
              {Math.min(page * pageSize, nodes.data?.total || 0)} of{" "}
              {nodes.data?.total || 0}
            </span>
            <button
              className="secondary"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              Trước
            </button>
            <span>
              Trang {page} / {pages}
            </span>
            <button
              className="secondary"
              disabled={page >= pages}
              onClick={() => setPage(page + 1)}
            >
              Sau
            </button>
          </div>
        </>
      )}
      {dialog && <Dialog title="Bắt đầu Compute Discovery" onClose={() => !submitting && setDialog(false)}><label>Tên job (không bắt buộc)<input autoFocus maxLength={150} value={jobName} onChange={e => setJobName(e.target.value)} /></label><p>Đã chọn {selected.size} node. Tối đa 20 node chạy đồng thời; các đợt còn lại sẽ chờ lần lượt.</p>{creationError && <p className="error" role="alert">{creationError}</p>}<div className="dialog-actions"><button className="secondary" disabled={submitting} onClick={() => setDialog(false)}>Hủy</button><button disabled={submitting} onClick={run}>{submitting ? "Đang khởi tạo…" : "Bắt đầu discovery"}</button></div></Dialog>}
      {saveDialog && <Dialog title="Lưu Saved View" onClose={()=>setSaveDialog(false)}><label>Tên view<input autoFocus maxLength={100} value={viewName} onChange={e=>setViewName(e.target.value)} /></label><div className="dialog-actions"><button className="secondary" onClick={()=>setSaveDialog(false)}>Hủy</button><button disabled={!viewName.trim()} onClick={saveView}>Lưu</button></div></Dialog>}
      {scheduleDialog && <Dialog title="Lập lịch Compute Discovery" onClose={()=>setScheduleDialog(false)}><label>Tên lịch<input autoFocus maxLength={150} value={scheduleName} onChange={e=>setScheduleName(e.target.value)} /></label><label>Chu kỳ<select value={scheduleMinutes} onChange={e=>setScheduleMinutes(e.target.value)}>{[[5,"5 phút"],[15,"15 phút"],[30,"30 phút"],[60,"1 giờ"],[240,"4 giờ"],[1440,"Hằng ngày"]].map(([value,label])=><option key={String(value)} value={String(value)}>{label}</option>)}</select></label><p>Đã chọn {selected.size} node. Lịch chỉ chạy khi application session còn active.</p><div className="dialog-actions"><button className="secondary" onClick={()=>setScheduleDialog(false)}>Hủy</button><button disabled={!scheduleName.trim()} onClick={createSchedule}>Tạo lịch</button></div></Dialog>}
      {(alerts.data||[]).length>0 && <div className="notice" role="alert">Cảnh báo lịch định kỳ: {(alerts.data||[]).map((x:any)=>x.message).join(" ")}</div>}
      {(schedules.data||[]).filter((x:any)=>x.operation==="COMPUTE_DISCOVERY").length>0 && <p className="notice">Lịch định kỳ: {(schedules.data||[]).filter((x:any)=>x.operation==="COMPUTE_DISCOVERY").map((x:any)=>`${x.name} (${x.interval_minutes} phút)`).join(", ")}</p>}
    </section>
  );
}
function DiscoveryReport() {
  const [view, setView] = useState<"groups" | "nodes" | "history" | "changes">("groups"), [search, setSearch] = useState(""), [status, setStatus] = useState(""), [jobId, setJobId] = useState(""), [page, setPage] = useState(1), [selected, setSelected] = useState<Set<number>>(new Set()), [group, setGroup] = useState<any>(), [exportNotice,setExportNotice]=useState("");
  const summary = useQuery({ queryKey: ["discovery-summary"], queryFn: () => api.get("/compute-discovery/report").then(r => r.data) });
  const jobs = useQuery({ queryKey: ["discovery-filter-jobs"], queryFn: () => api.get("/compute-discovery/jobs").then(r => r.data.items) });
  const data = useQuery({ queryKey: ["discovery-report", view, search, status, jobId, page], queryFn: () => api.get(`/compute-discovery/report/${view}`, { params: { page, page_size: 50, search: search || undefined, status: status || undefined, job_id: jobId || undefined } }).then(r => r.data) });
  const exports = useQuery({ queryKey:["background-exports"], queryFn:()=>api.get("/exports").then(r=>r.data.items), refetchInterval: q=>(q.state.data||[]).some((x:any)=>["QUEUED","RUNNING"].includes(x.status))?2000:false });
  const rows = data.data?.items || [];
  const exportRows = async () => { const result=await api.post("/exports",{export_type:"COMPUTE_DISCOVERY",payload:{search:search||undefined,status:status||undefined,job_id:jobId||undefined,node_ids:selected.size?[...selected]:undefined}}); setExportNotice(`Đã tạo export nền ${result.data.id}. File sẽ sẵn sàng trong Jobs xuất.`); exports.refetch(); };
  const switchView = (next: "groups" | "nodes" | "history" | "changes") => { setView(next); setPage(1); setSelected(new Set()); };
  return (
    <section>
      <header>
        <div><h1>Compute Discovery Report</h1><p>Review LLDP discovery results and group Teleport nodes by their detected compute host.</p></div>
        <button onClick={exportRows}>Export {selected.size ? "Selected" : "Current Filter"}</button>
      </header>
      <div className="cards"><Card title="Total Nodes Scanned" value={summary.data?.total_nodes_scanned}/><Card title="Compute Found" value={summary.data?.compute_found}/><Card title="Unique Computes" value={summary.data?.unique_computes}/><Card title="No LLDP / Unknown" value={summary.data?.no_lldp}/><Card title="Error" value={summary.data?.error}/></div>
      <div className="toolbar"><button className={view === "groups" ? "active" : "secondary"} onClick={() => switchView("groups")}>Compute Groups</button><button className={view === "nodes" ? "active" : "secondary"} onClick={() => switchView("nodes")}>Nodes</button><button className={view === "history" ? "active" : "secondary"} onClick={() => switchView("history")}>History</button><button className={view === "changes" ? "active" : "secondary"} onClick={() => switchView("changes")}>Thay đổi</button><input aria-label="Tìm báo cáo discovery" placeholder="Compute, hostname, IP, labels or job" value={search} onChange={e => {setSearch(e.target.value);setPage(1)}}/><select aria-label="Lọc trạng thái" value={status} onChange={e => {setStatus(e.target.value);setPage(1)}}><option value="">All statuses</option><option>SUCCESS</option><option>NO_LLDP</option><option>UNREACHABLE</option><option>ERROR</option></select><select aria-label="Lọc job" value={jobId} onChange={e => {setJobId(e.target.value);setPage(1)}}><option value="">All jobs</option>{(jobs.data || []).map((x:any) => <option key={x.job_id} value={x.job_id}>{x.job_name}</option>)}</select></div>
      {exportNotice && <p className="notice">{exportNotice}</p>}
      {(exports.data||[]).filter((x:any)=>x.export_type==="COMPUTE_DISCOVERY").slice(0,3).map((x:any)=><p className="notice" key={x.id}>Export {x.id.slice(0,8)}: <Badge status={x.status}/>{x.status==="COMPLETED" && <button className="secondary" onClick={()=>download(`/exports/${x.id}/download`)}>Tải file</button>}</p>)}
      {group && <div className="progress"><header><h2>{group.compute}</h2><button className="secondary" onClick={() => setGroup(undefined)}>Close</button></header><table><thead><tr><th>Node Name</th><th>IP</th><th>Labels</th><th>Discovery Job</th><th>LLDP NIC</th><th>Scanned At</th><th>Status</th></tr></thead><tbody>{group.nodes.map((x:any) => <tr key={x.node_id}><td>{x.hostname}</td><td>{x.address || "—"}</td><td><Labels labels={x.labels}/></td><td>{x.job_name}</td><td>{x.nic || "—"}</td><td>{time(x.discovered_at)}</td><td><Badge status={x.status}/></td></tr>)}</tbody></table></div>}
      {data.isLoading ? <p>Loading discovery report…</p> : view === "groups" ? <table><thead><tr><th>Compute</th><th>Nodes</th><th>Status</th><th>Last Scan</th><th>Action</th></tr></thead><tbody>{rows.map((x:any) => <tr key={x.compute}><td>{x.compute}</td><td>{x.node_count} — {x.node_names.join(", ")}</td><td><Badge status={x.status}/></td><td>{time(x.last_scan)}</td><td><button className="secondary" onClick={() => setGroup(x)}>View</button></td></tr>)}</tbody></table> : <table><thead><tr><th><input aria-label="Chọn tất cả node" type="checkbox" checked={rows.length > 0 && rows.every((x:any) => selected.has(x.node_id))} onChange={() => setSelected(rows.length && rows.every((x:any) => selected.has(x.node_id)) ? new Set() : new Set(rows.map((x:any) => x.node_id)))}/></th>{view === "history" && <th>Job ID</th>}{view === "changes" && <th>Thay đổi</th>}<th>Node Name</th><th>IP</th><th>Compute</th><th>NIC</th><th>Status</th><th>Job</th><th>Scanned At</th><th>Error</th></tr></thead><tbody>{rows.map((x:any) => <tr key={`${x.node_id}-${x.discovered_at}`}><td><input aria-label={`Chọn ${x.hostname}`} type="checkbox" checked={selected.has(x.node_id)} onChange={() => setSelected(old => {const next=new Set(old);next.has(x.node_id)?next.delete(x.node_id):next.add(x.node_id);return next})}/></td>{view === "history" && <td>{x.job_id}</td>}{view === "changes" && <td>{x.change_type}{x.previous_compute ? `: ${x.previous_compute} → ${x.compute || "—"}` : ""}</td>}<td>{x.hostname}</td><td>{x.address || "—"}</td><td>{x.compute || "—"}</td><td>{x.nic || "—"}</td><td><Badge status={x.status}/></td><td>{x.job_name}</td><td>{time(x.discovered_at)}</td><td>{x.detail || "—"}</td></tr>)}</tbody></table>}
      <div className="pagination"><button className="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page}</span><button className="secondary" disabled={page * 50 >= (data.data?.total || 0)} onClick={() => setPage(page + 1)}>Next</button></div>
    </section>
  );
}
type Page =
  | "overview"
  | "nodes"
  | "process-scan"
  | "compute-discovery"
  | "service-configuration"
  | "jobs"
  | "reports"
  | "config-report"
  | "discovery-report"
  | "help";

const pagePaths: Record<Page, string> = {
  overview: "/overview",
  nodes: "/nodes",
  "process-scan": "/process-scan",
  "compute-discovery": "/compute-discovery",
  "service-configuration": "/service-configuration",
  jobs: "/jobs",
  reports: "/reports",
  "config-report": "/reports/service-configuration",
  "discovery-report": "/reports/compute-discovery",
  help: "/help",
};
const pageFromPath = (path: string): Page =>
  (Object.entries(pagePaths).find(([, value]) => value === path)?.[0] as Page) || "overview";

function Overview({ navigate }: { navigate: (page: Page) => void }) {
  const nodes = useQuery({ queryKey: ["overview-nodes"], queryFn: () => api.get("/nodes", { params: { page: 1, page_size: 1 } }).then((r) => r.data) });
  const scans = useQuery({ queryKey: ["overview-scans"], queryFn: () => api.get("/reports/summary").then((r) => r.data) });
  const discovery = useQuery({ queryKey: ["overview-discovery"], queryFn: () => api.get("/compute-discovery/report").then((r) => r.data) });
  return <section>
    <header><div><h1>Tổng quan</h1><p className="page-intro">Theo dõi nhanh node, kết quả quét tiến trình và Compute Discovery.</p></div></header>
    <div className="cards overview-cards">
      <Card title="Tổng số node" value={nodes.data?.total ?? "—"} />
      <Card title="Node có cảnh báo" value={scans.data?.warning ?? scans.data?.warning_nodes ?? "—"} />
      <Card title="Compute đã phát hiện" value={discovery.data?.compute_found ?? "—"} />
      <Card title="Lỗi discovery" value={discovery.data?.error ?? "—"} />
    </div>
    <div className="overview-actions" aria-label="Lối tắt vận hành">
      <button onClick={() => navigate("nodes")}>Xem node</button>
      <button onClick={() => navigate("process-scan")}>Quét tiến trình</button>
      <button onClick={() => navigate("compute-discovery")}>Compute Discovery</button>
      <button className="secondary" onClick={() => navigate("jobs")}>Theo dõi jobs</button>
    </div>
  </section>;
}

function Reports({ page, navigate, initialHost, onBack }: { page: Page; navigate: (page: Page) => void; initialHost?: number; onBack: () => void }) {
  return <section className="reports-page">
    <nav className="report-nav" aria-label="Các loại báo cáo">
      <button className={page === "reports" ? "active" : "secondary"} aria-current={page === "reports" ? "page" : undefined} onClick={() => navigate("reports")}>Quét tiến trình</button>
      <button className={page === "config-report" ? "active" : "secondary"} aria-current={page === "config-report" ? "page" : undefined} onClick={() => navigate("config-report")}>Cấu hình dịch vụ</button>
      <button className={page === "discovery-report" ? "active" : "secondary"} aria-current={page === "discovery-report" ? "page" : undefined} onClick={() => navigate("discovery-report")}>Compute Discovery</button>
    </nav>
    {page === "config-report" ? <ConfigReport /> : page === "discovery-report" ? <DiscoveryReport /> : <ReportUI initialHost={initialHost} onBack={onBack} />}
  </section>;
}

function App() {
  const [logged, setLogged] = useState(false), [authLoading,setAuthLoading]=useState(true), [role,setRole]=useState<AppRole>("VIEWER"),
    [page, setPage] = useState<Page>(() => pageFromPath(window.location.pathname)),
    [reportHost, setReportHost] = useState<number>();
  const navigate = (next: Page, replace = false) => {
    const method = replace ? "replaceState" : "pushState";
    history[method](null, "", pagePaths[next]);
    setPage(next);
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  };
  useEffect(() => {
    if (window.location.pathname === "/") history.replaceState(null, "", pagePaths.overview);
    const onPopState = () => setPage(pageFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  useEffect(()=>{let mounted=true;const session=localStorage.getItem("teleport_session");if(!session){setAuthLoading(false);return}api.get("/auth/status").then((r)=>{if(mounted){setRole((r.data.role || "VIEWER") as AppRole);setLogged(true)}}).catch(()=>localStorage.removeItem("teleport_session")).finally(()=>{if(mounted)setAuthLoading(false)});return()=>{mounted=false}},[]);
  if(authLoading)return <main className="login"><p>Đang xác minh phiên đăng nhập…</p></main>;
  if (!logged) return <Login ok={(nextRole) => { setRole(nextRole); setLogged(true); }} />;
  const openReport = (id: number) => { setReportHost(id); navigate("reports"); };
  const menu: Array<{ page: Page; label: string }> = [
    { page: "overview", label: "Tổng quan" },
    { page: "nodes", label: "Nodes" },
    { page: "process-scan", label: "Quét tiến trình" },
    { page: "compute-discovery", label: "Compute Discovery" },
    { page: "service-configuration", label: "Cấu hình dịch vụ" },
    { page: "jobs", label: "Jobs" },
    { page: "reports", label: "Báo cáo" },
    { page: "help", label: "Trợ giúp" },
  ];
  const menuPage = ["config-report", "discovery-report"].includes(page) ? "reports" : page;
  return <div className="shell">
    <a className="skip-link" href="#main-content">Bỏ qua điều hướng</a>
    <aside>
      <h2>Teleport Scanner</h2>
      <nav aria-label="Điều hướng chính">
        {menu.map((item) => <button key={item.page} className={menuPage === item.page ? "active" : ""} aria-current={menuPage === item.page ? "page" : undefined} onClick={() => { setReportHost(undefined); navigate(item.page); }}>{item.label}</button>)}
      </nav>
      <button className="logout" onClick={async () => { try { await api.post("/auth/logout"); } finally { localStorage.removeItem("teleport_session"); setLogged(false); } }}>Đăng xuất</button>
    </aside>
    <main id="main-content" tabIndex={-1}>
      {page === "overview" ? <Overview navigate={navigate} />
        : page === "nodes" ? <Nodes openReport={openReport} role={role} />
        : page === "process-scan" ? <Nodes openReport={openReport} role={role} scanMode />
        : page === "compute-discovery" ? <ComputeDiscovery role={role} />
        : page === "service-configuration" ? <ServiceConfig role={role} />
        : page === "jobs" ? <Jobs />
        : page === "help" ? <Criteria />
        : <Reports page={page} navigate={navigate} initialHost={reportHost} onBack={() => setReportHost(undefined)} />}
    </main>
  </div>;
}
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={new QueryClient()}>
    <App />
  </QueryClientProvider>,
);
