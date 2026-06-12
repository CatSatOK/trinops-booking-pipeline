/* Admin panel: list bookings, review ONHOLD queue, accept/reject. */

const state = { bookings: [], filter: "", selected: null };

const tbody = document.getElementById("bookings-body");
const emptyState = document.getElementById("empty-state");
const drawer = document.getElementById("drawer");
const backdrop = document.getElementById("drawer-backdrop");
const drawerContent = document.getElementById("drawer-content");

async function loadBookings() {
  const url = state.filter ? `/bookings?status=${state.filter}` : "/bookings";
  const resp = await fetch(url);
  state.bookings = await resp.json();
  renderTable();
}

function renderTable() {
  tbody.innerHTML = "";
  emptyState.classList.toggle("hidden", state.bookings.length > 0);
  for (const b of state.bookings) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>#${b.id}</td>
      <td>${esc(b.client_name) || "<span class='muted'>unknown</span>"}</td>
      <td>${esc(b.service_type) || "—"}</td>
      <td>${b.requested_date || "—"}</td>
      <td>${b.requested_time ? b.requested_time.slice(0, 5) : "—"}</td>
      <td><span class="badge badge-${b.status}">${b.status}</span></td>
      <td>${b.status === "ONHOLD" ? "<span class='muted'>review &rsaquo;</span>" : ""}</td>`;
    tr.addEventListener("click", () => openDrawer(b));
    tbody.appendChild(tr);
  }
}

function openDrawer(booking) {
  state.selected = booking;
  const editable = booking.status === "ONHOLD";
  const field = (label, name, value, type = "text") =>
    `<dt>${label}</dt><dd>${
      editable
        ? `<input name="${name}" type="${type}" value="${value ?? ""}">`
        : esc(value) || "—"
    }</dd>`;

  drawerContent.innerHTML = `
    <dl class="field-grid">
      <dt>Status</dt><dd><span class="badge badge-${booking.status}">${booking.status}</span></dd>
      ${field("Client name", "client_name", booking.client_name)}
      ${field("Client email", "client_email", booking.client_email, "email")}
      ${field("Service", "service_type", booking.service_type)}
      ${field("Date", "requested_date", booking.requested_date, "date")}
      ${field("Time", "requested_time", booking.requested_time, "time")}
      ${field("Location", "location", booking.location)}
      <dt>Thread</dt><dd>${esc(booking.gmail_thread_id)}</dd>
      <dt>Calendar event</dt><dd>${esc(booking.calendar_event_id) || "—"}</dd>
      <dt>Invoice</dt><dd>${esc(booking.invoice_path) || "—"}</dd>
    </dl>
    ${booking.onhold_reason ? `<p class="reason">On hold: ${esc(booking.onhold_reason)}</p>` : ""}
    <h3 style="font-size:0.8rem;color:var(--muted);margin-bottom:6px;">ORIGINAL EMAIL</h3>
    <div class="snippet">${esc(booking.raw_email_snippet)}</div>
    ${
      editable
        ? `<div class="drawer-actions">
             <button class="btn btn-accept" id="accept-btn">Accept booking</button>
             <button class="btn btn-reject" id="reject-btn">Reject</button>
           </div>
           <p class="error-msg hidden" id="action-error"></p>`
        : ""
    }`;

  if (editable) {
    document.getElementById("accept-btn").addEventListener("click", acceptSelected);
    document.getElementById("reject-btn").addEventListener("click", rejectSelected);
  }
  drawer.classList.remove("hidden");
  backdrop.classList.remove("hidden");
}

function closeDrawer() {
  drawer.classList.add("hidden");
  backdrop.classList.add("hidden");
  state.selected = null;
}

async function acceptSelected() {
  const payload = {};
  drawerContent.querySelectorAll("input").forEach((input) => {
    if (input.value) payload[input.name] = input.value;
  });
  await patchSelected(`/bookings/${state.selected.id}/accept`, payload);
}

async function rejectSelected() {
  await patchSelected(`/bookings/${state.selected.id}/reject`, null);
}

async function patchSelected(url, payload) {
  const resp = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: payload ? JSON.stringify(payload) : null,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const el = document.getElementById("action-error");
    el.textContent = err.detail || `Request failed (${resp.status})`;
    el.classList.remove("hidden");
    return;
  }
  closeDrawer();
  await loadBookings();
}

function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

document.querySelectorAll(".filter").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.filter = btn.dataset.status;
    loadBookings();
  })
);
document.getElementById("refresh-btn").addEventListener("click", loadBookings);
document.getElementById("drawer-close").addEventListener("click", closeDrawer);
backdrop.addEventListener("click", closeDrawer);

loadBookings();
setInterval(loadBookings, 15000);
