"use strict";

(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = { token: sessionStorage.getItem("flightops-token"), user: null, incidents: [], flights: [], operators: [], page: "incidents", pageNumber: 1, pageSize: 20, total: 0, flightOptions: [], editFlight: null, loading: false, generation: 0, detailGeneration: 0, formGeneration: 0, form: null };
  const statuses = { OPEN: "Açık", IN_PROGRESS: "İşlemde", RESOLVED: "Çözüldü" };
  const kinds = { DELAY: "Gecikme", CANCELLATION: "İptal" };
  const priorities = { LOW: "Düşük", NORMAL: "Normal", HIGH: "Yüksek", CRITICAL: "Kritik" };
  const eventNames = { CREATED: "Incident oluşturuldu", ASSIGNED: "Operatöre atandı", STARTED: "Çalışma başlatıldı", RESOLVED: "Incident çözüldü", PRIORITY_CHANGED: "Öncelik değiştirildi" };
  const fieldNames = { username: "Kullanıcı adı", password: "Parola", old_password: "Mevcut parola", new_password: "Yeni parola", priority: "Öncelik", flight_number: "Uçuş numarası", departure_airport_code: "Kalkış havalimanı", arrival_airport_code: "Varış havalimanı", scheduled_departure: "Kalkış zamanı", scheduled_arrival: "Varış zamanı", flight: "Uçuş", kind: "Tür", description: "Açıklama", operator_id: "Operatör", resolution_notes: "Çözüm notu", status: "Durum", assigned_to: "Atanan operatör" };
  const messages = {
    "Unable to log in with provided credentials.": "Kullanıcı adı veya parola yanlış.",
    "This field is required.": "Bu alan zorunludur.",
    "This field may not be blank.": "Bu alan boş bırakılamaz.",
    "Arrival must be after departure.": "Varış zamanı kalkıştan sonra olmalıdır.",
    "Origin and destination must differ.": "Kalkış ve varış havalimanları farklı olmalıdır.",
    "Use a three-letter uppercase IATA code.": "Üç büyük harften oluşan havalimanı kodu girin (ör. IST).",
    "The fields flight_number, scheduled_departure must make a unique set.": "Bu uçuş numarası ve kalkış zamanı için zaten bir uçuş var.",
    "Only open incidents can be assigned.": "Yalnızca açık kayıtlar atanabilir.",
    "Only open incidents can be started.": "Yalnızca açık kayıtlar başlatılabilir.",
    "Assign an operator before starting work.": "İşi başlatmadan önce bir operatör atayın.",
    "Only in-progress incidents can be resolved.": "Yalnızca işlemdeki kayıtlar çözülebilir.",
    "Resolution notes are required.": "Çözüm notu zorunludur.",
    "Resolved incidents cannot change priority.": "Çözülmüş kayıtların önceliği değiştirilemez.",
  };
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const date = (value) => value ? new Date(value).toLocaleString("tr-TR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
  const badge = (status) => `<span class="badge ${escape(status)}">${escape(statuses[status] || status)}</span>`;
  const kind = (value) => `<span class="kind ${escape(value)}"><span aria-hidden="true">${value === "DELAY" ? "◷" : "⊘"}</span>${escape(kinds[value] || value)}</span>`;
  const isLead = () => state.user?.role === "team_lead";
  const priorityBadge = (value) => `<span class="priority ${escape(value)}">${escape(priorities[value] || value)}</span>`;
  const priorityOptions = (value) => Object.entries(priorities).map(([key, label]) => `<option value="${key}" ${value === key ? "selected" : ""}>${label}</option>`).join("");
  const duration = (seconds) => {
    const minutes = Math.floor(seconds / 60);
    if (minutes < 1) return "1 dk'dan az";
    if (minutes < 60) return `${minutes} dk`;
    const hours = Math.floor(minutes / 60);
    return hours < 24 ? `${hours} sa ${minutes % 60} dk` : `${Math.floor(hours / 24)} gün ${hours % 24} sa`;
  };
  const localDateTime = (value) => {
    const time = new Date(value);
    return new Date(time.getTime() - time.getTimezoneOffset() * 60000).toISOString().slice(0, 23);
  };

  function errorText(data) {
    if (typeof data === "string") return messages[data] || data;
    if (Array.isArray(data)) return data.map(errorText).join("\n");
    return Object.entries(data || {}).map(([key, value]) => `${fieldNames[key] ? fieldNames[key] + ": " : ""}${errorText(value)}`).join("\n");
  }

  async function api(path, { method = "GET", body, authenticated = true } = {}) {
    let response;
    try {
      response = await fetch(`/api/${path}`, {
        method, headers: { "Content-Type": "application/json", ...(authenticated && state.token ? { Authorization: `Token ${state.token}` } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new Error("Sunucuya ulaşılamadı. Bağlantını kontrol edip tekrar dene.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 429) throw new Error("Çok fazla giriş denemesi yapıldı. Bir dakika bekleyip tekrar dene.");
      if (response.status === 401 && authenticated) {
        logout();
        throw new Error("Oturumun sona erdi. Yeniden giriş yap.");
      }
      if (response.status === 403) throw new Error("Bu işlemi yapmak için yetkin yok. Ekip sorumlusu veya operatör rolünü kontrol et.");
      if (response.status === 404) {
        const error = new Error("Kayıt bulunamadı veya bu kayda erişim yetkin yok. Listeyi yenile.");
        error.status = 404;
        throw error;
      }
      if (response.status >= 500) throw new Error("Sunucuda bir sorun oluştu. Biraz sonra tekrar dene.");
      throw new Error(errorText(data) || "İşlem tamamlanamadı. Bilgileri kontrol et.");
    }
    return data;
  }

  let toastTimer;
  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $("#toast").textContent = message;
    $("#toast").classList.toggle("error", error);
    $("#toast").hidden = false;
    toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5000);
  }

  function logout() {
    clearTimeout(searchTimer);
    clearTimeout(flightSearchTimer);
    state.token = null;
    state.user = null;
    state.incidents = [];
    state.flights = [];
    state.operators = [];
    state.flightOptions = [];
    state.total = 0;
    state.pageNumber = 1;
    state.generation++;
    state.detailGeneration++;
    sessionStorage.removeItem("flightops-token");
    document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
    $("#workspace").hidden = true;
    $("#login-screen").hidden = false;
    $("#login-form").reset();
    $("#login-error").hidden = true;
    $("#search").value = "";
    $("#status-filter").value = "";
    $("#kind-filter").value = "";
    $("#priority-filter").value = "";
    $("#table-body").replaceChildren();
    $("#detail-content").replaceChildren();
    $("#password-form").reset();
    $("#login-form [name=username]").focus();
  }

  async function enterWorkspace() {
    state.user = await api("auth/me/");
    $("#profile-name").textContent = state.user.username;
    $("#profile-role").textContent = isLead() ? "Ekip sorumlusu" : "Operatör";
    $("#avatar").textContent = state.user.username.slice(0, 2).toLocaleUpperCase("tr-TR");
    $("#scope-note").textContent = isLead() ? "Ekip görünümü" : "Bana atanan kayıtlar";
    $("#today").textContent = new Date().toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" });
    document.querySelectorAll("[data-lead]").forEach((element) => { element.hidden = !isLead(); });
    $("#login-screen").hidden = true;
    $("#workspace").hidden = false;
    setPage("incidents");
    await load();
  }

  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.target.querySelector("button[type=submit]");
    const data = Object.fromEntries(new FormData(event.target));
    button.disabled = true;
    $("#login-error").hidden = true;
    try {
      const result = await api("auth/token/", { method: "POST", body: data, authenticated: false });
      state.token = result.token;
      sessionStorage.setItem("flightops-token", result.token);
      await enterWorkspace();
      event.target.reset();
    } catch (error) {
      logout();
      $("#login-error").textContent = error.message;
      $("#login-error").hidden = false;
    } finally {
      button.disabled = false;
    }
  });
  $("#logout").addEventListener("click", async () => {
    $("#logout").disabled = true;
    try {
      await api("auth/logout/", { method: "POST" });
      logout();
      toast("Oturumun sunucuda kapatıldı.");
    } catch (error) {
      toast(error.message, true);
    } finally {
      $("#logout").disabled = false;
    }
  });

  $("#change-password").addEventListener("click", () => {
    $("#password-form").reset();
    $("#password-error").hidden = true;
    $("#password-dialog").showModal();
  });
  $("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    $("#password-error").hidden = true;
    if (data.new_password !== data.confirmation) {
      $("#password-error").textContent = "Yeni parolalar eşleşmiyor.";
      $("#password-error").hidden = false;
      return;
    }
    const controls = [...event.target.closest("dialog").querySelectorAll("button")];
    $("#password-dialog").dataset.busy = "true";
    controls.forEach((button) => { button.disabled = true; });
    try {
      await api("auth/password/", { method: "POST", body: { old_password: data.old_password, new_password: data.new_password } });
      logout();
      toast("Parolan değiştirildi. Yeni parolanla tekrar giriş yap.");
    } catch (error) {
      $("#password-error").textContent = error.message;
      $("#password-error").hidden = false;
    } finally {
      $("#password-dialog").dataset.busy = "false";
      controls.forEach((button) => { button.disabled = false; });
    }
  });

  async function load() {
    const generation = ++state.generation;
    state.loading = true;
    $("#refresh").disabled = true;
    $("#load-error").hidden = true;
    render();
    try {
      const params = new URLSearchParams({ page: state.pageNumber, page_size: state.pageSize, ordering: $("#ordering").value, search: $("#search").value.trim() });
      if (state.page === "incidents") {
        for (const field of ["status", "kind", "priority"]) {
          if ($(`#${field}-filter`).value) params.set(field, $(`#${field}-filter`).value);
        }
      }
      const page = state.page;
      const [data, summary, operators] = await Promise.all([
        api(`${page}/?${params}`), api("incidents/summary/"), isLead() ? api("operators/") : Promise.resolve([]),
      ]);
      if (generation !== state.generation) return;
      state[page] = data.results;
      Object.assign(state, { total: data.count, operators });
      $("#nav-count").textContent = summary.total;
      $("#stat-total").textContent = summary.total;
      for (const [status, id] of [["OPEN", "open"], ["IN_PROGRESS", "progress"], ["RESOLVED", "resolved"]]) {
        $(`#stat-${id}`).textContent = summary[status.toLowerCase()];
      }
    } catch (error) {
      if (generation === state.generation) {
        if (error.status === 404 && state.pageNumber > 1) {
          state.pageNumber = 1;
          return load();
        }
        $("#load-error").textContent = error.message;
        $("#load-error").hidden = false;
      }
    } finally {
      if (generation === state.generation) {
        state.loading = false;
        $("#refresh").disabled = false;
        render();
      }
    }
  }

  function setPage(page) {
    if (page === "flights" && !isLead()) return;
    state.page = page;
    state.pageNumber = 1;
    const flights = page === "flights";
    document.querySelectorAll("[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === page));
    $("#page-title").textContent = flights ? "Uçuşlar" : "Incident kayıtları";
    $("#breadcrumb-page").textContent = $("#page-title").textContent;
    $("#page-subtitle").textContent = flights ? "Uçuş planlarını yönet, operasyon kayıtlarını bir arada tut." : isLead() ? "Ekibinin iş akışını takip et, operasyonu kesintisiz sürdür." : "Sana atanan işleri takip et, çözümleri ekibinle paylaş.";
    $("#records-title").textContent = flights ? "Uçuş planı" : "Tüm incident kayıtları";
    $("#new-incident").hidden = !isLead() || flights;
    $("#new-flight").hidden = !isLead() || !flights;
    $("#stats").hidden = flights;
    $("#incident-filters").hidden = flights;
    $("#search").value = "";
    $("#ordering").innerHTML = flights ? '<option value="scheduled_departure">Kalkış: en erken</option><option value="-scheduled_departure">Kalkış: en geç</option><option value="flight_number">Uçuş numarası</option>' : '<option value="-created_at">En yeni kayıtlar</option><option value="created_at">En eski kay?tlar</option><option value="-priority">Öncelik: en yüksek</option><option value="-updated_at">Son işlem zamanı</option>';
    $("#search").placeholder = flights ? "Uçuş numarası veya havalimanı ara…" : "Uçuş, açıklama veya operatör ara…";
    render();
  }

  function render() {
    const flights = state.page === "flights";
    const source = flights ? state.flights : state.incidents;
    const rows = source;
    $("#table-head").innerHTML = flights ? "<tr><th>Uçuş</th><th>Güzergâh</th><th>Planlanan kalkış</th><th>Planlanan varış</th><th>İşlem</th></tr>" : "<tr><th>Uçuş / Kayıt</th><th>Tür / Öncelik</th><th>Durum / Bekleme</th><th>Operatör</th><th>Son işlem</th><th>İşlem</th></tr>";
    $("#empty-state").hidden = state.loading || rows.length > 0;
    $("#record-count").textContent = `${state.total} kayıt`;
    const pageCount = Math.max(1, Math.ceil(state.total / state.pageSize));
    $("#page-number").textContent = `${state.pageNumber} / ${pageCount}`;
    $("#previous-page").disabled = state.loading || state.pageNumber <= 1;
    $("#next-page").disabled = state.loading || state.pageNumber >= pageCount;
    $("#table-summary").textContent = `${state.total ? (state.pageNumber - 1) * state.pageSize + 1 : 0}–${Math.min(state.pageNumber * state.pageSize, state.total)} / ${state.total} kayıt · Yerel saat`;
    if (state.loading) {
      $("#table-body").innerHTML = `<tr><td colspan="${flights ? 5 : 6}" class="loading-cell">Kayıtlar yükleniyor…</td></tr>`;
      return;
    }
    const filtered = $("#search").value || (!flights && ["status", "kind", "priority"].some((field) => $(`#${field}-filter`).value));
    $("#empty-title").textContent = filtered ? "Eşleşen kayıt bulunamadı" : flights ? "Henüz uçuş yok" : "Henüz incident yok";
    $("#empty-message").textContent = filtered ? "Aramanı veya filtrelerini değiştirerek tekrar dene." : isLead() ? "İlk kaydını üstteki oluşturma düğmesiyle ekleyebilirsin." : "Sana atanan incident kayıtları burada görünecek.";
    $("#table-body").innerHTML = rows.map((item) => {
      if (flights) return `<tr><td><strong class="flight-number">${escape(item.flight_number)}</strong><span class="cell-secondary">Uçuş #${item.id}</span></td><td>${escape(item.departure_airport_code)} <span class="muted">→</span> ${escape(item.arrival_airport_code)}</td><td>${escape(date(item.scheduled_departure))}</td><td>${escape(date(item.scheduled_arrival))}</td><td><button class="detail-button" data-flight="${item.id}">Düzenle</button></td></tr>`;
      const flight = item.flight_details;
      return `<tr><td><strong class="flight-number">${escape(flight.flight_number)} <span class="muted">· #${item.id}</span></strong><span class="cell-secondary">${escape(flight.departure_airport_code)} → ${escape(flight.arrival_airport_code)}</span><span class="incident-description" title="${escape(item.description)}">${escape(item.description)}</span></td><td>${kind(item.kind)}<span class="cell-secondary">${priorityBadge(item.priority)}</span></td><td>${badge(item.status)}<span class="cell-secondary">${duration(item.waiting_seconds)} ${item.status === "OPEN" ? "bekliyor" : "bekledi"}</span></td><td>${item.assigned_to ? `<span class="operator-cell"><span class="mini-avatar">${escape(item.assigned_to.slice(0, 2).toLocaleUpperCase("tr-TR"))}</span>${escape(item.assigned_to)}</span>` : '<span class="unassigned">— Atanmadı</span>'}</td><td><span class="operator-cell">${escape(date(item.updated_at))}</span><span class="cell-secondary">Açılış: ${escape(date(item.created_at))}</span></td><td><button class="detail-button" data-incident="${item.id}" aria-label="${escape(flight.flight_number)} incident ${item.id} detayını aç">Detay ↗</button></td></tr>`;
    }).join("");
  }

  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => { setPage(button.dataset.page); load(); }));
  let searchTimer;
  const reloadFirstPage = () => { state.pageNumber = 1; load(); };
  $("#search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(reloadFirstPage, 300); });
  ["#status-filter", "#kind-filter", "#priority-filter", "#ordering"].forEach((selector) => $(selector).addEventListener("change", reloadFirstPage));
  $("#page-size").addEventListener("change", () => { state.pageSize = Number($("#page-size").value); reloadFirstPage(); });
  $("#previous-page").addEventListener("click", () => { if (state.pageNumber > 1) { state.pageNumber--; load(); } });
  $("#next-page").addEventListener("click", () => { state.pageNumber++; load(); });
  $("#refresh").addEventListener("click", () => load());
  $("#table-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-incident]");
    if (button) openDetail(Number(button.dataset.incident));
    const flight = event.target.closest("[data-flight]");
    if (flight) openForm("flight", Number(flight.dataset.flight));
  });
  document.querySelectorAll(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
  document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("cancel", (event) => {
    if (dialog.dataset.busy === "true") event.preventDefault();
  }));
  $("#detail-dialog").addEventListener("close", () => { state.detailGeneration++; });
  $("#form-dialog").addEventListener("close", () => { state.formGeneration++; clearTimeout(flightSearchTimer); });

  async function openForm(type, flightId = null) {
    if (!isLead()) return;
    if (state.loading) return toast("Kayıtların yüklenmesini bekle.");
    const generation = state.generation;
    const formGeneration = ++state.formGeneration;
    if (type === "incident") {
      try {
        const data = await api("flights/?page_size=20&ordering=-scheduled_departure");
        if (generation !== state.generation || formGeneration !== state.formGeneration || !isLead()) return;
        state.flightOptions = data.results;
        if (!data.count) {
          toast("Incident açmadan önce bir uçuş oluştur.");
          setPage("flights");
          return openForm("flight");
        }
      } catch (error) {
        return toast(error.message, true);
      }
    }
    state.form = type;
    state.editFlight = flightId ? state.flights.find((flight) => flight.id === flightId) : null;
    $("#record-form").reset();
    $("#form-error").hidden = true;
    $("#form-title").textContent = type === "flight" ? state.editFlight ? "Uçuşu düzenle" : "Yeni uçuş oluştur" : "Yeni incident aç";
    $("#form-submit").textContent = state.editFlight ? "Değişiklikleri kaydet" : "Oluştur";
    $("#form-fields").innerHTML = type === "flight" ? `
      <label class="full-width">Uçuş numarası<input name="flight_number" placeholder="Örn. TK1234" maxlength="8" required></label>
      <label>Kalkış havalimanı<input name="departure_airport_code" placeholder="IST" maxlength="3" pattern="[A-Za-z]{3}" required></label>
      <label>Varış havalimanı<input name="arrival_airport_code" placeholder="LHR" maxlength="3" pattern="[A-Za-z]{3}" required></label>
      <label>Planlanan kalkış<input type="datetime-local" step="0.001" name="scheduled_departure" required></label>
      <label>Planlanan varış<input type="datetime-local" step="0.001" name="scheduled_arrival" required></label>
      <span class="field-hint full-width">Zamanları cihazının yerel saat diliminde gir. Kayıt sırasında UTC'ye dönüştürülür.</span>` : `
      <label class="full-width">Uçuş ara<input type="search" id="flight-search" placeholder="Uçuş numarası veya havalimanı…"><span class="field-hint">En fazla 20 eşleşme gösterilir. Aradığın uçuş yoksa aramayı daralt.</span></label>
      <label class="full-width">Uçuş<select name="flight" required>${flightOptions()}</select></label>
      <label class="full-width">Incident türü<select name="kind"><option value="DELAY">Gecikme</option><option value="CANCELLATION">İptal</option></select></label>
      <label class="full-width">Öncelik<select name="priority">${priorityOptions("NORMAL")}</select></label>
      <label class="full-width">Açıklama<textarea name="description" placeholder="Ne oldu? Operasyon ekibinin bilmesi gerekenleri yaz…" required></textarea></label>`;
    if (state.editFlight) {
      for (const field of ["flight_number", "departure_airport_code", "arrival_airport_code", "scheduled_departure", "scheduled_arrival"]) {
        $(`#record-form [name=${field}]`).value = field.startsWith("scheduled_") ? localDateTime(state.editFlight[field]) : state.editFlight[field];
      }
    }
    let lookupGeneration = 0;
    $("#flight-search")?.addEventListener("input", () => {
      const lookup = ++lookupGeneration;
      clearTimeout(flightSearchTimer);
      const query = $("#flight-search").value;
      $("#record-form [name=flight]").disabled = true;
      $("#form-submit").disabled = true;
      flightSearchTimer = setTimeout(async () => {
        try {
          const data = await api(`flights/?page_size=20&ordering=-scheduled_departure&search=${encodeURIComponent(query)}`);
          if (!$("#form-dialog").open || formGeneration !== state.formGeneration || state.form !== "incident" || lookup !== lookupGeneration) return;
          state.flightOptions = data.results;
          $("#record-form [name=flight]").innerHTML = flightOptions();
          $("#record-form [name=flight]").disabled = false;
          $("#form-submit").disabled = false;
          $("#form-error").hidden = true;
        } catch (error) {
          if ($("#form-dialog").open && formGeneration === state.formGeneration && lookup === lookupGeneration) {
            $("#form-error").textContent = error.message;
            $("#form-error").hidden = false;
          }
        }
      }, 300);
    });
    $("#form-submit").disabled = false;
    $("#form-dialog").showModal();
  }
  let flightSearchTimer;
  const flightOptions = () => `<option value="">Uçuş seç…</option>${state.flightOptions.map((flight) => `<option value="${flight.id}">${escape(flight.flight_number)} · ${escape(flight.departure_airport_code)} → ${escape(flight.arrival_airport_code)} · ${escape(date(flight.scheduled_departure))}</option>`).join("")}`;
  $("#new-flight").addEventListener("click", () => openForm("flight"));
  $("#new-incident").addEventListener("click", () => openForm("incident"));
  $("#record-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    const type = state.form;
    const editing = state.editFlight;
    const controls = [...$("#form-dialog").querySelectorAll("button")];
    $("#form-dialog").dataset.busy = "true";
    $("#form-error").hidden = true;
    controls.forEach((control) => { control.disabled = true; });
    try {
      if (type === "flight") {
        for (const field of ["flight_number", "departure_airport_code", "arrival_airport_code"]) data[field] = data[field].trim().toUpperCase();
        for (const field of ["scheduled_departure", "scheduled_arrival"]) data[field] = editing && new Date(data[field]).getTime() === new Date(editing[field]).getTime() ? editing[field] : new Date(data[field]).toISOString();
      } else {
        data.flight = Number(data.flight);
      }
      await api(type === "flight" ? editing ? `flights/${editing.id}/` : "flights/" : "incidents/", { method: editing ? "PATCH" : "POST", body: data });
      $("#form-dialog").close();
      toast(type === "flight" ? editing ? "Uçuş planı güncellendi." : "Uçuş planı oluşturuldu." : "Incident açıldı. Detay ekranından operatöre atayabilirsin.");
      await load();
    } catch (error) {
      $("#form-error").textContent = error.message;
      $("#form-error").hidden = false;
    } finally {
      $("#form-dialog").dataset.busy = "false";
      controls.forEach((control) => { control.disabled = false; });
    }
  });

  async function openDetail(id) {
    const generation = ++state.detailGeneration;
    const dialog = $("#detail-dialog");
    $("#detail-title").textContent = `Incident #${id}`;
    $("#detail-content").innerHTML = '<p class="muted">Detay ve olay geçmişi yükleniyor…</p>';
    if (!dialog.open) dialog.showModal();
    try {
      const [incident, events] = await Promise.all([api(`incidents/${id}/`), api(`incidents/${id}/events/`)]);
      if (generation !== state.detailGeneration) return;
      const flight = incident.flight_details;
      $("#detail-title").textContent = `${flight.flight_number} · Incident #${id}`;
      const canAct = isLead() || incident.assigned_to === state.user.username;
      let actions = "";
      if (isLead() && incident.status !== "RESOLVED") {
        actions += `<form data-action="priority"><label>Öncelik<select name="priority">${priorityOptions(incident.priority)}</select></label><button class="button secondary" type="submit">Önceliği kaydet</button></form>`;
      }
      if (isLead() && incident.status === "OPEN") {
        actions += `<form data-action="assign"><label>Operatör ataması<select name="operator_id" required><option value="">Operatör seç…</option>${state.operators.map((operator) => `<option value="${operator.id}" ${operator.username === incident.assigned_to ? "selected" : ""}>${escape(operator.username)}${operator.first_name ? ` · ${escape(operator.first_name)} ${escape(operator.last_name)}` : ""}</option>`).join("")}</select></label><button class="button secondary" type="submit" ${state.operators.length ? "" : "disabled"}>Atamayı kaydet</button></form>`;
        if (!state.operators.length) actions += '<p class="field-hint">Aktif operatör bulunamadı. Django yönetiminden Operators grubuna kullanıcı ekleyin.</p>';
      }
      if (canAct && incident.status === "OPEN") actions += `<div><button class="button primary" id="start-incident" ${incident.assigned_to ? "" : "disabled"}>↗ İşi başlat</button>${incident.assigned_to ? "" : '<p class="field-hint" style="margin-top:9px">Başlatmak için önce bir operatör atanmalı.</p>'}</div>`;
      if (canAct && incident.status === "IN_PROGRESS") actions += '<form data-action="resolve" class="resolve-form"><label>Çözüm notu<textarea name="resolution_notes" placeholder="Sorun nasıl çözüldü? Yapılan işlemleri özetle…" required maxlength="10000"></textarea></label><button class="button primary" type="submit">✓ Çözümü tamamla</button></form>';
      $("#detail-content").innerHTML = `
        <div class="detail-meta">${badge(incident.status)} ${kind(incident.kind)} ${priorityBadge(incident.priority)}</div>
        <p class="detail-description">${escape(incident.description)}</p>
        <dl class="detail-grid"><div><dt>Güzergâh</dt><dd>${escape(flight.departure_airport_code)} → ${escape(flight.arrival_airport_code)}</dd></div><div><dt>Planlanan kalkış</dt><dd>${escape(date(flight.scheduled_departure))}</dd></div><div><dt>Oluşturan</dt><dd>${escape(incident.created_by)}</dd></div><div><dt>Atanan operatör</dt><dd>${escape(incident.assigned_to || "Henüz atanmadı")}</dd></div><div><dt>${incident.status === "OPEN" ? "Açık bekleme süresi" : "Başlatılana kadar bekleme"}</dt><dd>${duration(incident.waiting_seconds)}</dd></div><div><dt>Son işlem zamanı</dt><dd>${escape(date(incident.updated_at))}</dd></div></dl>
        ${incident.resolution_notes ? `<div class="resolution"><strong>Çözüm notu</strong>${escape(incident.resolution_notes)}</div>` : ""}
        ${actions ? `<section class="detail-actions" aria-label="Incident işlemleri">${actions}</section>` : ""}
        <p id="detail-error" class="form-error detail-error" role="alert" hidden></p>
        <h3 class="history-heading">Olay geçmişi <span class="muted">· ${events.length}</span></h3>
        <ol class="timeline">${events.map((event) => `<li><div class="event-heading"><strong>${escape(eventNames[event.event_type] || event.event_type)}</strong><time datetime="${escape(event.created_at)}">${escape(date(event.created_at))}</time></div><p><strong>${escape(event.actor)}</strong> · ${event.previous_status ? `${escape(statuses[event.previous_status])} → ` : ""}${escape(statuses[event.new_status] || "")}</p>${event.details?.priority ? `<p>Öncelik: ${event.details.previous_priority ? `${escape(priorities[event.details.previous_priority])} → ` : ""}${escape(priorities[event.details.priority])}</p>` : ""}${event.details?.assigned_operator ? `<p>Atanan operatör: ${escape(event.details.assigned_operator)}</p>` : ""}${event.details?.resolution_notes ? `<p>${escape(event.details.resolution_notes)}</p>` : ""}</li>`).join("")}</ol>`;
      $("#start-incident")?.addEventListener("click", () => performAction(id, "start", {}));
      dialog.querySelectorAll("form[data-action]").forEach((form) => form.addEventListener("submit", (event) => {
        event.preventDefault();
        const body = Object.fromEntries(new FormData(form));
        if (form.dataset.action === "assign") body.operator_id = Number(body.operator_id);
        performAction(id, form.dataset.action, body);
      }));
    } catch (error) {
      if (generation !== state.detailGeneration) return;
      $("#detail-content").replaceChildren();
      const paragraph = document.createElement("p");
      paragraph.className = "form-error";
      paragraph.setAttribute("role", "alert");
      paragraph.textContent = error.message;
      $("#detail-content").append(paragraph);
    }
  }

  async function performAction(id, action, body) {
    const dialog = $("#detail-dialog");
    const controls = [...dialog.querySelectorAll("button, select, textarea")].map((control) => [control, control.disabled]);
    controls.forEach(([control]) => { control.disabled = true; });
    $("#detail-error").hidden = true;
    try {
      await api(`incidents/${id}/${action}/`, { method: "POST", body });
      toast({ priority: "Öncelik güncellendi.", assign: "Operatör ataması kaydedildi.", start: "Çalışma başlatıldı.", resolve: "Incident çözüldü. Çözüm notun olay geçmişine eklendi." }[action]);
      await load();
      if (dialog.open && state.user) await openDetail(id);
    } catch (error) {
      if ($("#detail-error")) {
        $("#detail-error").textContent = error.message;
        $("#detail-error").hidden = false;
      }
    } finally {
      controls.forEach(([control, disabled]) => { if (control.isConnected) control.disabled = disabled; });
    }
  }

  if (state.token) enterWorkspace().catch((error) => { logout(); toast(error.message, true); });
})();
