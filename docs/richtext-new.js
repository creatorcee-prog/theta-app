  // Text with links, @mentions, and safe markdown (tables, task lists,
  // bold/italic/code, images). Built from DOM nodes — never innerHTML.
  function richText(text) {
    const root = document.createElement("div");
    root.className = "text";
    if (!text) return root;

    function linkEl(url) {
      const a = document.createElement("a");
      let clean = url.replace(/[).,!?]+$/, "");
      a.href = clean; a.target = "_blank"; a.rel = "noopener";
      try {
        const u = new URL(clean);
        a.textContent = u.hostname.replace(/^www\./, "") +
          (u.pathname.length > 1 ? u.pathname.slice(0, 28) + (u.pathname.length > 28 ? "…" : "") : "");
      } catch (_) { a.textContent = clean; }
      return a;
    }
    function atEl(name) {
      const s = document.createElement("span");
      s.className = "at"; s.textContent = name;
      return s;
    }
    function inline(s) {
      const frag = document.createDocumentFragment();
      const re = /(\*\*[^*]+\*\*)|(\*[^*]+\*)|(`[^`]+`)|(!\[[^\]]*\]\([^)]+\))|(https?:\/\/[^\s<]+)|(@[A-Za-z][\w-]*)/g;
      let last = 0, m;
      while ((m = re.exec(s))) {
        if (m.index > last) frag.append(s.slice(last, m.index));
        if (m[1]) {
          const b = document.createElement("strong");
          b.textContent = m[1].slice(2, -2);
          frag.append(b);
        } else if (m[2]) {
          const i = document.createElement("em");
          i.textContent = m[2].slice(1, -1);
          frag.append(i);
        } else if (m[3]) {
          const c = document.createElement("code");
          c.textContent = m[3].slice(1, -1);
          frag.append(c);
        } else if (m[4]) {
          const imgMatch = m[4].match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
          if (imgMatch) {
            const img = document.createElement("img");
            img.src = imgMatch[2];
            img.alt = imgMatch[1] || "";
            img.loading = "lazy";
            img.style.maxWidth = "100%";
            img.style.borderRadius = "8px";
            frag.append(img);
          } else frag.append(m[4]);
        } else if (m[5]) {
          frag.append(linkEl(m[5]));
          last = m.index + m[5].replace(/[).,!?]+$/, "").length;
          re.lastIndex = last;
          continue;
        } else if (m[6]) {
          frag.append(atEl(m[6]));
        }
        last = m.index + m[0].length;
      }
      if (last < s.length) frag.append(s.slice(last));
      return frag;
    }

    const lines = text.replace(/\r\n/g, "\n").split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];

      if (line.trim().startsWith("```")) {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        i++;
        const body = [];
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          body.push(lines[i]);
          i++;
        }
        code.textContent = body.join("\n");
        pre.append(code);
        root.append(pre);
        i++;
        continue;
      }

      if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s\-:|]+\\|/.test(lines[i + 1])) {
        const table = document.createElement("table");
        table.className = "md-table";
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");
        function cells(l) {
          return l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map(c => c.trim());
        }
        const headers = cells(line);
        const trh = document.createElement("tr");
        headers.forEach(h => {
          const th = document.createElement("th");
          th.append(inline(h));
          trh.append(th);
        });
        thead.append(trh);
        table.append(thead);
        i += 2;
        while (i < lines.length && lines[i].includes("|")) {
          const tr = document.createElement("tr");
          cells(lines[i]).forEach(c => {
            const td = document.createElement("td");
            td.append(inline(c));
            tr.append(td);
          });
          tbody.append(tr);
          i++;
        }
        table.append(tbody);
        root.append(table);
        continue;
      }

      const task = line.match(/^\s*[-*]\s+\[([ xX])\]\s+(.*)$/);
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (task || bullet) {
        const ul = document.createElement("ul");
        ul.className = task ? "task-list" : "";
        while (i < lines.length) {
          const t = lines[i].match(/^\s*[-*]\s+\[([ xX])\]\s+(.*)$/);
          const b = lines[i].match(/^\s*[-*]\s+(.*)$/);
          if (!t && !b) break;
          const li = document.createElement("li");
          if (t) {
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.disabled = true;
            cb.checked = t[1].toLowerCase() === "x";
            li.append(cb, " ");
            li.append(inline(t[2]));
            li.className = "task-item";
          } else {
            li.append(inline(b[1]));
          }
          ul.append(li);
          i++;
        }
        root.append(ul);
        continue;
      }

      if (!line.trim()) {
        root.append(document.createElement("br"));
        i++;
        continue;
      }

      const p = document.createElement("div");
      p.append(inline(line));
      root.append(p);
      i++;
    }
    return root;
  }
