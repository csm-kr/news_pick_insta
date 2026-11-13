// ego lite TaskSpace를 로컬 TCP JSON-lines로 중계한다. ego_harness.py가 entry 파일에서 serve(config)를 호출한다.
// 번역 로직은 Python(EgoSession)에 있고, 여기서는 Page/TaskSpace API를 그대로 노출만 한다.
// `taskSpace`는 ego-browser nodejs 런타임이 제공하는 전역이다.

const IDLE_EXIT_MS = 10 * 60 * 1000;

export async function openTask(config) {
  if (!config.profileId) return await taskSpace(config.space);
  const spaces = await listTaskSpaces();
  const existing = typeof config.space === "number"
    ? spaces.find((space) => space.id === config.space)
    : spaces.find((space) => space.taskId === config.space) || spaces.find((space) => space.name === config.space);
  if (existing && existing.profileId !== config.profileId) {
    throw new Error("News Pick ego profile mismatch; existing task space is not in the configured profile");
  }
  // profileId is creation-only. Resume by id without passing creation options.
  const task = existing
    ? await taskSpace(existing.id)
    : await taskSpace(config.space, { profileId: config.profileId });
  const current = existing || (await listTaskSpaces()).find((space) => space.id === task.spaceId);
  if (!current || current.profileId !== config.profileId) {
    throw new Error("News Pick ego profile mismatch; existing task space is not in the configured profile");
  }
  return task;
}

export async function serve(config) {
  const net = await import("node:net");
  const fs = await import("node:fs/promises");
  const task = await openTask(config);

  const page = (label) => {
    if (typeof label !== "string" || !/^p\d+$/.test(label)) throw new Error("invalid page label: " + label);
    return task.page(label);
  };

  async function handle(req) {
    switch (req.op) {
      case "tabs":
        return (await task.tabs()).map((t) => ({ label: t.label || null, url: t.url || "", title: t.title || "", active: !!t.active }));
      case "new_page":
        return { label: (await task.newPage()).label };
      case "goto":
        await page(req.page).goto(req.url, { timeout: req.timeout || 45000 });
        return {};
      case "close_page":
        await page(req.page).close();
        return {};
      case "page_cdp":
        return await page(req.page).cdp(req.method, req.params || {}, req.timeout ? { timeout: req.timeout } : undefined);
      case "task_cdp":
        return await task.cdp(req.method, req.params || {});
      case "space_info": {
        // 일일 보고용: 이 연결이 실제로 붙은 공간과 프로필
        const info = (await listTaskSpaces()).find((space) => space.id === task.spaceId) || {};
        return { spaceId: task.spaceId, name: info.name ?? null, profileId: info.profileId ?? null, profileName: info.profileName ?? null };
      }
      default:
        throw new Error("unknown op: " + req.op);
    }
  }

  let finish;
  const finished = new Promise((resolve) => (finish = resolve));
  let idle = setTimeout(() => finish("idle"), IDLE_EXIT_MS);

  const server = net.createServer((sock) => {
    sock.setEncoding("utf8");
    let buffer = "";
    let chain = Promise.resolve();
    sock.on("data", (chunk) => {
      buffer += chunk;
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        if (!line.trim()) continue;
        // 요청은 받은 순서대로 하나씩 실행한다(CDP 입력 순서 보존).
        chain = chain.then(async () => {
          clearTimeout(idle);
          idle = setTimeout(() => finish("idle"), IDLE_EXIT_MS);
          let req;
          try {
            req = JSON.parse(line);
          } catch (error) {
            sock.write(JSON.stringify({ ok: false, error: "bad json" }) + "\n");
            return;
          }
          if (req.op === "exit") {
            sock.write(JSON.stringify({ id: req.id, ok: true, result: {} }) + "\n");
            finish("exit");
            return;
          }
          try {
            const result = await handle(req);
            sock.write(JSON.stringify({ id: req.id, ok: true, result: result ?? {} }) + "\n");
          } catch (error) {
            sock.write(JSON.stringify({ id: req.id, ok: false, error: String((error && error.message) || error) }) + "\n");
          }
        });
      }
    });
    sock.on("close", () => finish("closed"));
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  await fs.writeFile(config.portFile, String(server.address().port));
  const reason = await finished;
  clearTimeout(idle);
  server.close();
  console.log("[ego_bridge] stopped: " + reason);
  process.exit(0);
}
