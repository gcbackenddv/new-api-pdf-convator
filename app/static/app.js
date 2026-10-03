const responseStatus = document.querySelector("#response-status");
const responseMessage = document.querySelector("#response-message");
const responseBody = document.querySelector("#response-body");

function showResponse(status, message, body, kind = "") {
  responseStatus.textContent = status;
  responseStatus.className = `response-status ${kind}`.trim();
  responseMessage.textContent = message;
  responseBody.textContent = body;
}

function filenameFromResponse(response) {
  const disposition = response.headers.get("content-disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  if (encoded) return decodeURIComponent(encoded[1]);
  if (plain) return plain[1];
  return "download";
}

async function sendRequest(url, options = {}, download = false) {
  showResponse("SENDING", `${options.method || "GET"} ${url}`, "Waiting for the server…", "pending");
  try {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";

    if (download && response.ok && !contentType.includes("json")) {
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filenameFromResponse(response);
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      showResponse(
        `${response.status} ${response.statusText}`,
        "Conversion complete. Your file download has started.",
        `Downloaded ${link.download} (${blob.size.toLocaleString()} bytes).`
      );
      return;
    }

    const responseText = await response.text();
    let body = responseText;
    if (contentType.includes("json")) {
      try {
        body = JSON.stringify(JSON.parse(responseText), null, 2);
      } catch {
        body = responseText || "The API returned an empty response.";
      }
    }
    showResponse(
      `${response.status} ${response.statusText}`,
      response.ok ? "Request completed successfully." : "The API returned an error.",
      body,
      response.ok ? "" : "error"
    );
  } catch (error) {
    showResponse(
      "NETWORK ERROR",
      "Could not reach the API. Make sure the app is running and try again.",
      error instanceof Error ? error.message : String(error),
      "error"
    );
  }
}

document.querySelectorAll("[data-get]").forEach((button) => {
  button.addEventListener("click", () => sendRequest(button.dataset.get));
});

const heicFilesInput = document.querySelector("#heic-files");
const heicSelection = document.querySelector("#heic-selection");

heicFilesInput.addEventListener("change", () => {
  const files = Array.from(heicFilesInput.files || []);
  heicSelection.classList.toggle("has-files", files.length > 0);
  if (files.length === 0) {
    heicSelection.textContent = "No images selected. Each uploaded image becomes one PDF page.";
    return;
  }

  const names = files.map((file) => file.name).join(", ");
  heicSelection.textContent = `${files.length} image${files.length === 1 ? "" : "s"} selected: ${names}`;
});

document.querySelectorAll("form[data-endpoint]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    event.preventDefault();

    const query = new URLSearchParams();
    form.querySelectorAll("[data-query]").forEach((field) => {
      if (field.type === "checkbox") {
        query.set(field.name, String(field.checked));
      } else if (field.value !== "") {
        query.set(field.name, field.value);
      }
    });

    const suffix = query.size ? `?${query.toString()}` : "";
    const body = new FormData();
    form.querySelectorAll('input[type="file"]').forEach((input) => {
      Array.from(input.files || []).forEach((file) => body.append(input.name, file));
    });

    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    sendRequest(`${form.dataset.endpoint}${suffix}`, { method: "POST", body }, form.dataset.download === "true")
      .finally(() => { button.disabled = false; });
  });
});
