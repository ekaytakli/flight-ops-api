"use strict";

(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = { token: sessionStorage.getItem("flightops-token"), user: null, incidents: [], flights: [], operators: [], page: "incidents", loading: false, generation: 0, detailGeneration: 0, form: null };
  const statuses = { OPEN: "Açık", IN_PROGRESS: "İşlemde", RESOLVED: "Çözüldü" };
  const kinds = { DELAY: "Gecikme", CANCELLATION: "İptal" };
  const eventNames = { CREATED: "Incident oluşturuldu", ASSIGNED: "Operatöre atandı", STARTED: "Çalışma başlatıldı", RESOLVED: "Incident çözüldü" };
  const fieldNames = { username: "Kullanıcı adı", password: "Parola", flight_number: "Uçuş numarası", departure_airport_code: "Kalkış havalimanı", arrival_airport_code: "Varış havalimanı", scheduled_departure: "Kalkış zamanı", scheduled_arrival: "Varış zamanı", flight: "Uçuş", kind: "Tür", description: "Açıklama", operator_id: "Operatör", resolution_notes: "Çözüm notu", status: "Durum", assigned_to: "Atanan operatör" };
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
  };
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const date = (value) => value ? new Date(value).toLocaleString("tr-TR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
  const badge = (status) => `<span class="badge ${escape(status)}">${escape(statuses[status] || status)}</span>`;
  const kind = (value) => `<span class="kind ${escape(value)}"><span aria-hidden="true">${value === "DELAY" ? "◷" : "⊘"}</span>${escape(kinds[value] || value)}</span>`;
  const isLead = () => state.user?.role === "team_lead";

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
      if (response.status === 401 && authenticated) {
        logout();
        throw new Error("Oturumun sona erdi. Yeniden giriş yap.");
      }
      if (response.status === 403) throw new Error("Bu işlemi yapmak için yetkin yok. Ekip sorumlusu veya operatör rolünü kontrol et.");
      if (response.status === 404) throw new Error("Kayıt bulunamadı veya bu kayda erişim yetkin yok. Listeyi yenile.");
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
    state.token = null;
    state.user = null;
    state.incidents = [];
    state.flights = [];
    state.operators = [];
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
    $("#table-body").replaceChildren();
    $("#detail-content").replaceChildren();
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
  $("#logout").addEventListener("click", logout);

  async function load() {
    const generation = ++state.generation;
    state.loading = true;
    $("#refresh").disabled = true;
    $("#load-error").hidden = true;
    render();
    try {
      const [incidents, flights, operators] = await Promise.all([
        api("incidents/"), isLead() ? api("flights/") : Promise.resolve([]), isLead() ? api("operators/") : Promise.resolve([]),
      ]);
      if (generation !== state.generation) return;
      Object.assign(state, { incidents, flights, operators });
      $("#nav-count").textContent = incidents.length;
      $("#stat-total").textContent = incidents.length;
      for (const [status, id] of [["OPEN", "open"], ["IN_PROGRESS", "progress"], ["RESOLVED", "resolved"]]) {
        $(`#stat-${id}`).textContent = incidents.filter((incident) => incident.status === status).length;
      }
    } catch (error) {
      if (generation === state.generation) {
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
    $("#search").placeholder = flights ? "Uçuş numarası veya havalimanı ara…" : "Uçuş, açıklama veya operatör ara…";
    render();
  }

  function render() {
    const flights = state.page === "flights";
    const source = flights ? state.flights : state.incidents;
    const search = $("#search").value.trim().toLocaleLowerCase("tr-TR");
    const rows = source.filter((item) => {
      const flight = flights ? item : item.flight_details;
      const haystack = [item.id, flight?.flight_number, flight?.departure_airport_code, flight?.arrival_airport_code, item.description, item.assigned_to].join(" ").toLocaleLowerCase("tr-TR");
      return haystack.includes(search) && (flights || ((!$("#status-filter").value || item.status === $("#status-filter").value) && (!$("#kind-filter").value || item.kind === $("#kind-filter").value)));
    });
    $("#table-head").innerHTML = flights ? "<tr><th>Uçuş</th><th>Güzergâh</th><th>Planlanan kalkış</th><th>Planlanan varış</th></tr>" : "<tr><th>Uçuş / Kayıt</th><th>Tür</th><th>Durum</th><th>Operatör</th><th>Oluşturulma</th><th><span class='muted'>İşlem</span></th></tr>";
    $("#empty-state").hidden = state.loading || rows.length > 0;
    $("#record-count").textContent = `${source.length} kayıt`;
    $("#table-summary").textContent = `${rows.length} / ${source.length} kayıt gösteriliyor · Saatler cihazının yerel saat dilimindedir`;
    if (state.loading) {
      $("#table-body").innerHTML = `<tr><td colspan="${flights ? 4 : 6}" class="loading-cell">Kayıtlar yükleniyor…</td></tr>`;
      return;
    }
    $("#empty-title").textContent = source.length ? "Eşleşen kayıt bulunamadı" : flights ? "Henüz uçuş yok" : "Henüz incident yok";
    $("#empty-message").textContent = source.length ? "Aramanı veya filtrelerini değiştirerek tekrar dene." : isLead() ? "İlk kaydını üstteki oluşturma düğmesiyle ekleyebilirsin." : "Sana atanan incident kayıtları burada görünecek.";
    $("#table-body").innerHTML = rows.map((item) => {
      if (flights) return `<tr><td><strong class="flight-number">${escape(item.flight_number)}</strong><span class="cell-secondary">Uçuş #${item.id}</span></td><td>${escape(item.departure_airport_code)} <span class="muted">→</span> ${escape(item.arrival_airport_code)}</td><td>${escape(date(item.scheduled_departure))}</td><td>${escape(date(item.scheduled_arrival))}</td></tr>`;
      const flight = item.flight_details;
      return `<tr><td><strong class="flight-number">${escape(flight.flight_number)} <span class="muted">· #${item.id}</span></strong><span class="cell-secondary">${escape(flight.departure_airport_code)} → ${escape(flight.arrival_airport_code)}</span><span class="incident-description" title="${escape(item.description)}">${escape(item.description)}</span></td><td>${kind(item.kind)}</td><td>${badge(item.status)}</td><td>${item.assigned_to ? `<span class="operator-cell"><span class="mini-avatar">${escape(item.assigned_to.slice(0, 2).toLocaleUpperCase("tr-TR"))}</span>${escape(item.assigned_to)}</span>` : '<span class="unassigned">— Atanmadı</span>'}</td><td><span class="operator-cell">${escape(date(item.created_at))}</span></td><td><button class="detail-button" data-incident="${item.id}" aria-label="${escape(flight.flight_number)} incident ${item.id} detayını aç">Detay ↗</button></td></tr>`;
    }).join("");
  }

  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => setPage(button.dataset.page)));
  ["#search", "#status-filter", "#kind-filter"].forEach((selector) => $(selector).addEventListener("input", render));
  $("#refresh").addEventListener("click", load);
  $("#table-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-incident]");
    if (button) openDetail(Number(button.dataset.incident));
  });
  document.querySelectorAll(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
  $("#detail-dialog").addEventListener("close", () => { state.detailGeneration++; });

  function openForm(type) {
    if (!isLead()) return;
    if (state.loading) return toast("Kayıtların yüklenmesini bekle.");
    if (type === "incident" && !state.flights.length) {
      toast("Incident açmadan önce bir uçuş oluştur.");
      setPage("flights");
      return openForm("flight");
    }
    state.form = type;
    $("#record-form").reset();
    $("#form-error").hidden = true;
    $("#form-title").textContent = type === "flight" ? "Yeni uçuş oluştur" : "Yeni incident aç";
    $("#form-fields").innerHTML = type === "flight" ? `
      <label class="full-width">Uçuş numarası<input name="flight_number" placeholder="Örn. TK1234" maxlength="8" required></label>
      <label>Kalkış havalimanı<input name="departure_airport_code" placeholder="IST" maxlength="3" pattern="[A-Za-z]{3}" required></label>
      <label>Varış havalimanı<input name="arrival_airport_code" placeholder="LHR" maxlength="3" pattern="[A-Za-z]{3}" required></label>
      <label>Planlanan kalkış<input type="datetime-local" name="scheduled_departure" required></label>
      <label>Planlanan varış<input type="datetime-local" name="scheduled_arrival" required></label>
      <span class="field-hint full-width">Zamanları cihazının yerel saat diliminde gir. Kayıt sırasında UTC'ye dönüştürülür.</span>` : `
      <label class="full-width">Uçuş<select name="flight" required><option value="">Uçuş seç…</option>${state.flights.map((flight) => `<option value="${flight.id}">${escape(flight.flight_number)} · ${escape(flight.departure_airport_code)} → ${escape(flight.arrival_airport_code)} · ${escape(date(flight.scheduled_departure))}</option>`).join("")}</select></label>
      <label class="full-width">Incident türü<select name="kind"><option value="DELAY">Gecikme</option><option value="CANCELLATION">İptal</option></select></label>
      <label class="full-width">Açıklama<textarea name="description" placeholder="Ne oldu? Operasyon ekibinin bilmesi gerekenleri yaz…" required></textarea></label>`;
    $("#form-dialog").showModal();
  }
  $("#new-flight").addEventListener("click", () => openForm("flight"));
  $("#new-incident").addEventListener("click", () => openForm("incident"));
  $("#record-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    const type = state.form;
    const button = $("#form-submit");
    $("#form-error").hidden = true;
    button.disabled = true;
    try {
      if (type === "flight") {
        for (const field of ["flight_number", "departure_airport_code", "arrival_airport_code"]) data[field] = data[field].trim().toUpperCase();
        for (const field of ["scheduled_departure", "scheduled_arrival"]) data[field] = new Date(data[field]).toISOString();
      } else {
        data.flight = Number(data.flight);
      }
      await api(type === "flight" ? "flights/" : "incidents/", { method: "POST", body: data });
      $("#form-dialog").close();
      toast(type === "flight" ? "Uçuş planı oluşturuldu." : "Incident açıldı. Detay ekranından operatöre atayabilirsin.");
      await load();
    } catch (error) {
      $("#form-error").textContent = error.message;
      $("#form-error").hidden = false;
    } finally {
      button.disabled = false;
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
      if (isLead() && incident.status === "OPEN") {
        actions += `<form data-action="assign"><label>Operatör ataması<select name="operator_id" required><option value="">Operatör seç…</option>${state.operators.map((operator) => `<option value="${operator.id}" ${operator.username === incident.assigned_to ? "selected" : ""}>${escape(operator.username)}${operator.first_name ? ` · ${escape(operator.first_name)} ${escape(operator.last_name)}` : ""}</option>`).join("")}</select></label><button class="button secondary" type="submit" ${state.operators.length ? "" : "disabled"}>Atamayı kaydet</button></form>`;
        if (!state.operators.length) actions += '<p class="field-hint">Aktif operatör bulunamadı. Django yönetiminden Operators grubuna kullanıcı ekleyin.</p>';
      }
      if (canAct && incident.status === "OPEN") actions += `<div><button class="button primary" id="start-incident" ${incident.assigned_to ? "" : "disabled"}>↗ İşi başlat</button>${incident.assigned_to ? "" : '<p class="field-hint" style="margin-top:9px">Başlatmak için önce bir operatör atanmalı.</p>'}</div>`;
      if (canAct && incident.status === "IN_PROGRESS") actions += '<form data-action="resolve" class="resolve-form"><label>Çözüm notu<textarea name="resolution_notes" placeholder="Sorun nasıl çözüldü? Yapılan işlemleri özetle…" required maxlength="10000"></textarea></label><button class="button primary" type="submit">✓ Çözümü tamamla</button></form>';
      $("#detail-content").innerHTML = `
        <div class="detail-meta">${badge(incident.status)} ${kind(incident.kind)}</div>
        <p class="detail-description">${escape(incident.description)}</p>
        <dl class="detail-grid"><div><dt>Güzergâh</dt><dd>${escape(flight.departure_airport_code)} → ${escape(flight.arrival_airport_code)}</dd></div><div><dt>Planlanan kalkış</dt><dd>${escape(date(flight.scheduled_departure))}</dd></div><div><dt>Oluşturan</dt><dd>${escape(incident.created_by)}</dd></div><div><dt>Atanan operatör</dt><dd>${escape(incident.assigned_to || "Henüz atanmadı")}</dd></div></dl>
        ${incident.resolution_notes ? `<div class="resolution"><strong>Çözüm notu</strong>${escape(incident.resolution_notes)}</div>` : ""}
        ${actions ? `<section class="detail-actions" aria-label="Incident işlemleri">${actions}</section>` : ""}
        <p id="detail-error" class="form-error detail-error" role="alert" hidden></p>
        <h3 class="history-heading">Olay geçmişi <span class="muted">· ${events.length}</span></h3>
        <ol class="timeline">${events.map((event) => `<li><div class="event-heading"><strong>${escape(eventNames[event.event_type] || event.event_type)}</strong><time datetime="${escape(event.created_at)}">${escape(date(event.created_at))}</time></div><p><strong>${escape(event.actor)}</strong> · ${event.previous_status ? `${escape(statuses[event.previous_status])} → ` : ""}${escape(statuses[event.new_status] || "")}</p>${event.details?.assigned_operator ? `<p>Atanan operatör: ${escape(event.details.assigned_operator)}</p>` : ""}${event.details?.resolution_notes ? `<p>${escape(event.details.resolution_notes)}</p>` : ""}</li>`).join("")}</ol>`;
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
      toast({ assign: "Operatör ataması kaydedildi.", start: "Çalışma başlatıldı.", resolve: "Incident çözüldü. Çözüm notun olay geçmişine eklendi." }[action]);
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
