const responseStatus = document.querySelector("#response-status");
const responseMessage = document.querySelector("#response-message");
const responseBody = document.querySelector("#response-body");

function showResponse(status, message, body, kind = "") {
  responseStatus.textContent = status;
  responseStatus.className = `response-status ${kind}`.trim();
  responseMessage.textContent = message;
  responseBody.textContent = body;
}

function filenameFromResponse(response, fallback = "download") {
  const disposition = response.headers.get("content-disposition") || "";
  const encoded = disposition.match(/filename\*=(?:UTF-8|utf-8)''([^;]+)/i);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  if (encoded) return decodeURIComponent(encoded[1]);
  if (plain) return plain[1];
  return fallback;
}

async function sendRequest(url, options = {}, download = false) {
  showResponse("SENDING", `${options.method || "GET"} ${url}`, "Waiting for the server…", "pending");
  try {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";

    if (download && response.ok) {
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      const flattenFormFields = response.headers.get("x-flatten-form-fields");
      const flattenAnnotations = response.headers.get("x-flatten-annotations");
      const signatureInvalidated = response.headers.get("x-signature-invalidated") === "true";
      const extractedImageCount = response.headers.get("x-extracted-image-count");
      const outputFormat = response.headers.get("x-output-format");
      const tableCount = response.headers.get("x-table-count");
      const extractionWarnings = response.headers.get("x-extraction-warnings");
      const ocrPages = response.headers.get("x-ocr-pages");
      const formatSuffix = outputFormat && outputFormat !== "original" ? `-${outputFormat}` : "";
      const defaultName = flattenFormFields !== null
        ? "flattened-document.pdf"
        : extractedImageCount !== null
          ? `extracted-images${formatSuffix}.zip`
          : tableCount !== null
            ? `extracted-tables${contentType.includes("json") ? ".json" : ""}`
          : "download";
      link.download = filenameFromResponse(response, defaultName);
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      const flattenMessage = flattenFormFields === null
        ? null
        : signatureInvalidated
          ? "Flattened PDF downloaded. Its digital signature was invalidated."
          : `Flattened PDF downloaded. Found ${flattenFormFields} form field${flattenFormFields === "1" ? "" : "s"} and ${flattenAnnotations || "0"} annotation${flattenAnnotations === "1" ? "" : "s"}.`;
      const tableMessage = tableCount === null
        ? null
        : `Extracted ${tableCount} table${tableCount === "1" ? "" : "s"}${extractionWarnings && extractionWarnings !== "0" ? ` with ${extractionWarnings} warning${extractionWarnings === "1" ? "" : "s"}` : ""}${ocrPages ? `. OCR used on page${ocrPages.includes(",") ? "s" : ""} ${ocrPages}` : ""}. Your download has started.`;
      const downloadMessage = flattenMessage
        || tableMessage
        || (extractedImageCount === null
          ? "Conversion complete. Your file download has started."
          : `Extracted ${extractedImageCount} embedded image${extractedImageCount === "1" ? "" : "s"}${outputFormat ? ` as ${outputFormat}` : ""}. Your download has started.`);
      const tableDetails = tableCount === null
        ? ""
        : `\nTables extracted: ${tableCount}\nWarnings: ${extractionWarnings || "0"}\nOCR pages: ${ocrPages || "none"}`;
      showResponse(
        `${response.status} ${response.statusText}`,
        downloadMessage,
        `Downloaded ${link.download} (${blob.size.toLocaleString()} bytes).${flattenFormFields === null ? "" : `\nForm fields found: ${flattenFormFields}\nAnnotations found: ${flattenAnnotations || "0"}\nSignature invalidated: ${signatureInvalidated ? "yes" : "no"}.`}${tableDetails}`
      );
      return;
    }

    const responseText = await response.text();
    let body = responseText;
    let message = response.ok ? "Request completed successfully." : "The API returned an error.";
    const tableCount = response.headers.get("x-table-count");
    const extractionWarnings = response.headers.get("x-extraction-warnings");
    const ocrPages = response.headers.get("x-ocr-pages");
    if (response.ok && tableCount !== null) {
      message = `Extracted ${tableCount} table${tableCount === "1" ? "" : "s"}${extractionWarnings && extractionWarnings !== "0" ? ` with ${extractionWarnings} warning${extractionWarnings === "1" ? "" : "s"}` : ""}${ocrPages ? `. OCR used on page${ocrPages.includes(",") ? "s" : ""} ${ocrPages}` : ""}.`;
    }
    if (contentType.includes("json")) {
      try {
        const parsed = JSON.parse(responseText);
        body = JSON.stringify(parsed, null, 2);
        if (!response.ok && typeof parsed.detail === "string") {
          message = parsed.detail;
        }
      } catch {
        body = responseText || "The API returned an empty response.";
      }
    }
    showResponse(
      `${response.status} ${response.statusText}`,
      message,
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

const deskewForm = document.querySelector('form[data-endpoint="/api/v1/pdf/deskew"]');
const deskewFileInput = deskewForm.querySelector("#deskew-file");
const deskewPages = deskewForm.querySelector("#deskew-pages");
const deskewAnglesInput = deskewForm.querySelector("#deskew-angles");
const deskewMode = deskewForm.querySelector("#deskew-mode");
const deskewSubmitButton = deskewForm.querySelector('button[type="submit"]');
let deskewSliders = [];

function updateDeskewMode() {
  const isManual = deskewMode.value === "manual";
  deskewSliders.forEach((slider) => { slider.disabled = !isManual; });
  deskewAnglesInput.disabled = !isManual;
}

deskewFileInput.addEventListener("change", async () => {
  const file = deskewFileInput.files?.[0];
  deskewPages.replaceChildren();
  deskewAnglesInput.value = "";
  deskewSliders = [];
  updateDeskewMode();
  if (!file) {
    return;
  }

  deskewSubmitButton.disabled = true;
  deskewPages.textContent = "Loading page previews…";
  const previewBody = new FormData();
  previewBody.append("file", file);
  try {
    const response = await fetch("/api/v1/pdf/deskew/preview", {
      method: "POST",
      body: previewBody,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Could not preview this PDF.");
    }

    const angles = payload.pages.map(() => 0);
    const fragment = document.createDocumentFragment();
    payload.pages.forEach(({ page, preview }, index) => {
      const card = document.createElement("section");
      card.className = "deskew-page";
      const heading = document.createElement("h4");
      heading.textContent = `Page ${page}`;
      const image = document.createElement("img");
      image.alt = `Preview of page ${page}`;
      image.src = `data:image/jpeg;base64,${preview}`;
      image.className = "deskew-page-preview";
      const label = document.createElement("label");
      label.className = "field-label";
      const output = document.createElement("output");
      output.textContent = "0.0°";
      label.append(`Clockwise angle: `, output);
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "-15";
      slider.max = "15";
      slider.step = "0.1";
      slider.value = "0";
      slider.disabled = deskewMode.value !== "manual";
      slider.setAttribute("aria-label", `Rotation angle for page ${page}`);
      slider.addEventListener("input", () => {
        angles[index] = Number(slider.value);
        output.textContent = `${angles[index].toFixed(1)}°`;
        image.style.transform = `rotate(${angles[index]}deg)`;
        deskewAnglesInput.value = JSON.stringify(angles);
      });
      label.append(slider);
      deskewSliders.push(slider);
      card.append(heading, image, label);
      fragment.append(card);
    });
    deskewAnglesInput.value = JSON.stringify(angles);
    deskewPages.replaceChildren(fragment);
  } catch (error) {
    deskewPages.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    deskewSubmitButton.disabled = false;
  }
});
deskewMode.addEventListener("change", updateDeskewMode);
updateDeskewMode();

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
    form.querySelectorAll("[data-form]").forEach((field) => {
      if (field.disabled) {
        return;
      }
      body.append(field.name, field.type === "checkbox" ? String(field.checked) : field.value);
    });

    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    sendRequest(`${form.dataset.endpoint}${suffix}`, { method: "POST", body }, form.dataset.download === "true")
      .finally(() => { button.disabled = false; });
  });
});
