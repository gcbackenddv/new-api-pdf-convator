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
      const flattenStamps = response.headers.get("x-flatten-stamps");
      const signatureInvalidated = response.headers.get("x-signature-invalidated") === "true";
      const extractedImageCount = response.headers.get("x-extracted-image-count");
      const outputFormat = response.headers.get("x-output-format");
      const tableCount = response.headers.get("x-table-count");
      const extractionWarnings = response.headers.get("x-extraction-warnings");
      const ocrPages = response.headers.get("x-ocr-pages");
      const ocrWords = response.headers.get("x-ocr-words");
      const ocrPagesSkipped = response.headers.get("x-ocr-pages-skipped");
      const removedPages = response.headers.get("x-removed-pages");
      const remainingPages = response.headers.get("x-remaining-pages");
      const originalPages = response.headers.get("x-original-pages");
      const removedPageNumbers = response.headers.get("x-removed-page-numbers");
      const pdfRepaired = response.headers.get("x-pdf-repaired");
      const pdfPages = response.headers.get("x-pdf-pages");
      const formatSuffix = outputFormat && outputFormat !== "original" ? `-${outputFormat}` : "";
      const defaultName = flattenFormFields !== null
        ? "flattened-document.pdf"
        : extractedImageCount !== null
          ? `extracted-images${formatSuffix}.zip`
          : tableCount !== null
            ? `extracted-tables${contentType.includes("json") ? ".json" : ""}`
            : removedPages !== null
              ? "cleaned-document.pdf"
              : pdfRepaired !== null
                ? "repaired-document.pdf"
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
          : `Flattened PDF downloaded. Found ${flattenFormFields} form field${flattenFormFields === "1" ? "" : "s"}, ${flattenAnnotations || "0"} annotation${flattenAnnotations === "1" ? "" : "s"}, and ${flattenStamps || "0"} stamp${flattenStamps === "1" ? "" : "s"}.`;
      const tableMessage = tableCount === null
        ? null
        : `Extracted ${tableCount} table${tableCount === "1" ? "" : "s"}${extractionWarnings && extractionWarnings !== "0" ? ` with ${extractionWarnings} warning${extractionWarnings === "1" ? "" : "s"}` : ""}${ocrPages ? `. OCR used on page${ocrPages.includes(",") ? "s" : ""} ${ocrPages}` : ""}. Your download has started.`;
      const searchableMessage = ocrWords === null
        ? null
        : `Searchable PDF created. OCR recognized ${Number(ocrWords).toLocaleString()} words across ${ocrPages || "0"} page${ocrPages === "1" ? "" : "s"}${ocrPagesSkipped && ocrPagesSkipped !== "0" ? `; skipped ${ocrPagesSkipped} page${ocrPagesSkipped === "1" ? "" : "s"} that already had text` : ""}. Your download has started.`;
      const blankPagesMessage = removedPages === null
        ? null
        : `Cleaned PDF downloaded. Removed ${removedPages} blank page${removedPages === "1" ? "" : "s"} (kept ${remainingPages} of ${originalPages}${removedPageNumbers && removedPageNumbers !== "[]" ? `; removed page numbers: ${removedPageNumbers}` : ""}).`;
      const repairMessage = pdfRepaired === null
        ? null
        : `Repaired PDF downloaded (${pdfPages || "unknown"} pages). ${pdfRepaired === "true" ? "Corrupted structures were successfully restored." : "Document structure is healthy and clean."}`;
      const downloadMessage = flattenMessage
        || tableMessage
        || searchableMessage
        || blankPagesMessage
        || repairMessage
        || (extractedImageCount === null
          ? "Conversion complete. Your file download has started."
          : `Extracted ${extractedImageCount} embedded image${extractedImageCount === "1" ? "" : "s"}${outputFormat ? ` as ${outputFormat}` : ""}. Your download has started.`);
      const tableDetails = tableCount === null
        ? ""
        : `\nTables extracted: ${tableCount}\nWarnings: ${extractionWarnings || "0"}\nOCR pages: ${ocrPages || "none"}`;
      const blankDetails = removedPages === null
        ? ""
        : `\nOriginal pages: ${originalPages}\nBlank pages removed: ${removedPages}\nRemaining pages: ${remainingPages}\nRemoved page numbers: ${removedPageNumbers || "[]"}`;
      const repairDetails = pdfRepaired === null
        ? ""
        : `\nTotal pages: ${pdfPages}\nRepaired: ${pdfRepaired}`;
      showResponse(
        `${response.status} ${response.statusText}`,
        downloadMessage,
        `Downloaded ${link.download} (${blob.size.toLocaleString()} bytes).${flattenFormFields === null ? "" : `\nForm fields found: ${flattenFormFields}\nAnnotations found: ${flattenAnnotations || "0"}\nSignature invalidated: ${signatureInvalidated ? "yes" : "no"}.`}${tableDetails}${blankDetails}${repairDetails}`
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

const pdfPreviewSource = document.querySelector("#pdf-preview-source");
const pdfPreviewFiles = document.querySelector("#pdf-preview-files");
const pdfPreviewEmpty = document.querySelector("#pdf-preview-empty");
const pdfPreviewFrame = document.querySelector("#pdf-preview-frame");
const pdfPreviewOpen = document.querySelector("#pdf-preview-open");
const pdfPreviewIndicator = document.querySelector(".preview-indicator");
const deskewForm = document.querySelector('form[data-endpoint="/api/v1/pdf/deskew"]');
const deskewFileInput = deskewForm.querySelector("#deskew-file");
const deskewPages = document.querySelector("#deskew-pages");
const deskewAnglesInput = deskewForm.querySelector("#deskew-angles");
const deskewMode = deskewForm.querySelector("#deskew-mode");
const deskewSubmitButton = deskewForm.querySelector('button[type="submit"]');
const deskewPreviewHeading = document.querySelector(".deskew-preview-heading");
const enhanceForm = document.querySelector('form[data-endpoint="/api/v1/pdf/enhance"]');
const enhanceFileInput = enhanceForm.querySelector("#enhance-file");
const enhancePreview = document.querySelector("#enhance-preview");
const enhancePreviewImage = document.querySelector("#enhance-preview-image");
const enhancePreviewMessage = document.querySelector("#enhance-preview-message");
let activePreviewForm = null;
let activePreviewUrl = null;
let deskewPreviewRequestId = 0;
let deskewSliders = [];
let enhancePreviewUrl = null;
let enhancePreviewController = null;
let enhancePreviewTimer = null;
let enhancePreviewRequestId = 0;

function cancelEnhancePreview() {
  window.clearTimeout(enhancePreviewTimer);
  enhancePreviewController?.abort();
  enhancePreviewController = null;
  enhancePreviewRequestId += 1;
}

function showPdfPreview(files, form, activeIndex = files.length - 1) {
  if (activePreviewUrl) {
    URL.revokeObjectURL(activePreviewUrl);
  }
  activePreviewForm = form;
  const operationName = form.closest(".operation-card")?.querySelector("h3")?.textContent.trim();
  pdfPreviewSource.textContent = operationName || "Selected PDF";
  pdfPreviewFiles.replaceChildren();
  pdfPreviewFiles.hidden = files.length < 2;
  const isDeskewForm = form === deskewForm;
  const isEnhanceForm = form === enhanceForm;
  if (isEnhanceForm) {
    cancelEnhancePreview();
  }
  if (!isEnhanceForm) {
    cancelEnhancePreview();
    if (enhancePreviewUrl) {
      URL.revokeObjectURL(enhancePreviewUrl);
      enhancePreviewUrl = null;
    }
    enhancePreviewImage.removeAttribute("src");
    enhancePreviewImage.hidden = true;
  }
  pdfPreviewFrame.hidden = isDeskewForm;
  deskewPages.hidden = !isDeskewForm;
  deskewPreviewHeading.hidden = !isDeskewForm;
  enhancePreview.hidden = !isEnhanceForm;
  files.forEach(({ file, label }, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pdf-preview-file";
    button.textContent = files.length > 1 ? `${label}: ${file.name}` : file.name;
    button.setAttribute("aria-pressed", String(index === activeIndex));
    button.addEventListener("click", () => showPdfPreview(files, form, index));
    pdfPreviewFiles.append(button);
  });

  const selected = files[activeIndex];
  activePreviewUrl = URL.createObjectURL(selected.file);
  pdfPreviewFrame.src = activePreviewUrl;
  pdfPreviewFrame.title = `Preview of ${selected.file.name}`;
  pdfPreviewFrame.hidden = isDeskewForm;
  pdfPreviewOpen.href = activePreviewUrl;
  pdfPreviewOpen.hidden = false;
  pdfPreviewEmpty.hidden = true;
  pdfPreviewIndicator.classList.add("has-file");
}

function clearPdfPreview(form) {
  if (activePreviewForm !== form) {
    return;
  }
  if (activePreviewUrl) {
    URL.revokeObjectURL(activePreviewUrl);
  }
  activePreviewForm = null;
  activePreviewUrl = null;
  pdfPreviewFrame.removeAttribute("src");
  pdfPreviewFrame.hidden = true;
  pdfPreviewOpen.removeAttribute("href");
  pdfPreviewOpen.hidden = true;
  pdfPreviewFiles.replaceChildren();
  pdfPreviewFiles.hidden = true;
  pdfPreviewSource.textContent = "Choose a PDF in any operation to preview it here.";
  pdfPreviewEmpty.hidden = false;
  pdfPreviewIndicator.classList.remove("has-file");
  deskewPages.hidden = true;
  deskewPreviewHeading.hidden = true;
  enhancePreview.hidden = true;
  cancelEnhancePreview();
  if (enhancePreviewUrl) {
    URL.revokeObjectURL(enhancePreviewUrl);
    enhancePreviewUrl = null;
  }
  enhancePreviewImage.removeAttribute("src");
  enhancePreviewImage.hidden = true;
}

document.querySelectorAll('input[type="file"][accept*=".pdf"]').forEach((input) => {
  input.addEventListener("change", () => {
    const form = input.closest("form");
    const files = Array.from(form.querySelectorAll('input[type="file"][accept*=".pdf"]'))
      .flatMap((fileInput) => {
        const label = Array.from(form.querySelectorAll("label[for]"))
          .find((candidate) => candidate.htmlFor === fileInput.id)?.textContent.trim();
        return Array.from(fileInput.files || []).map((file) => ({
          file,
          label: label || fileInput.name,
        }));
      });
    if (!files.length) {
      clearPdfPreview(form);
      return;
    }
    showPdfPreview(files, form);
    if (form === enhanceForm) {
      scheduleEnhancePreview();
    }
  });
});

function scheduleEnhancePreview() {
  if (activePreviewForm !== enhanceForm || !enhanceFileInput.files?.[0]) {
    return;
  }
  window.clearTimeout(enhancePreviewTimer);
  enhancePreviewTimer = window.setTimeout(refreshEnhancePreview, 250);
}

async function refreshEnhancePreview() {
  const file = enhanceFileInput.files?.[0];
  if (activePreviewForm !== enhanceForm || !file) {
    return;
  }

  enhancePreviewController?.abort();
  const controller = new AbortController();
  enhancePreviewController = controller;
  const requestId = ++enhancePreviewRequestId;
  const query = new URLSearchParams();
  enhanceForm.querySelectorAll("[data-query]").forEach((field) => {
    query.set(field.name, field.type === "checkbox" ? String(field.checked) : field.value);
  });
  const body = new FormData();
  body.append("file", file);
  enhancePreviewMessage.textContent = "Updating preview…";

  try {
    const response = await fetch(`/api/v1/pdf/enhance/preview?${query}`, {
      method: "POST",
      body,
      signal: controller.signal,
    });
    if (!response.ok) {
      const responseText = await response.text();
      let detail = responseText || "Could not update the enhancement preview.";
      try {
        detail = JSON.parse(responseText).detail || detail;
      } catch {
        // Keep the response text when the server did not return JSON.
      }
      throw new Error(detail);
    }

    const previewBlob = await response.blob();
    if (requestId !== enhancePreviewRequestId || activePreviewForm !== enhanceForm) {
      return;
    }
    if (enhancePreviewUrl) {
      URL.revokeObjectURL(enhancePreviewUrl);
    }
    enhancePreviewUrl = URL.createObjectURL(previewBlob);
    enhancePreviewImage.src = enhancePreviewUrl;
    enhancePreviewImage.hidden = false;
    enhancePreviewMessage.textContent = "Enhanced preview · Page 1";
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }
    if (requestId === enhancePreviewRequestId) {
      enhancePreviewMessage.textContent = error instanceof Error ? error.message : String(error);
    }
  } finally {
    if (requestId === enhancePreviewRequestId) {
      enhancePreviewController = null;
    }
  }
}

enhanceForm.querySelectorAll("[data-query]").forEach((field) => {
  field.addEventListener("input", scheduleEnhancePreview);
  field.addEventListener("change", scheduleEnhancePreview);
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

function updateDeskewMode() {
  const isManual = deskewMode.value === "manual";
  deskewSliders.forEach((slider) => { slider.disabled = false; });
  deskewAnglesInput.disabled = !isManual;
}

deskewFileInput.addEventListener("change", async () => {
  const file = deskewFileInput.files?.[0];
  const requestId = ++deskewPreviewRequestId;
  deskewPages.replaceChildren();
  deskewAnglesInput.value = "";
  deskewSliders = [];
  updateDeskewMode();
  if (!file) {
    deskewPages.hidden = true;
    deskewPreviewHeading.hidden = true;
    return;
  }

  deskewPages.hidden = false;
  deskewPreviewHeading.hidden = false;
  pdfPreviewFrame.hidden = true;
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
    if (requestId !== deskewPreviewRequestId || activePreviewForm !== deskewForm) {
      return;
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
      label.append(`Rotation angle: `, output);
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "-180";
      slider.max = "180";
      slider.step = "1";
      slider.value = "0";
      slider.disabled = false;
      slider.setAttribute("aria-label", `Rotation angle for page ${page}, from minus 180 to plus 180 degrees`);
      slider.addEventListener("input", () => {
        deskewMode.value = "manual";
        updateDeskewMode();
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
    if (requestId === deskewPreviewRequestId && activePreviewForm === deskewForm) {
      deskewPages.textContent = error instanceof Error ? error.message : String(error);
    }
  } finally {
    if (requestId === deskewPreviewRequestId) {
      deskewSubmitButton.disabled = false;
    }
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

// ==========================================================================
// Drag & Drop Enhancements (Commented out)
// ==========================================================================
/*
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function updateDropZone(zone, files) {
  const prompt = zone.querySelector(".drop-zone-prompt");
  const info = zone.querySelector(".drop-zone-file-info");
  const filename = zone.querySelector(".drop-zone-filename");
  const filesize = zone.querySelector(".drop-zone-filesize");
  const badge = zone.querySelector(".drop-zone-file-badge");

  if (!files || files.length === 0) {
    if (prompt) prompt.hidden = false;
    if (info) info.hidden = true;
    return;
  }

  if (prompt) prompt.hidden = true;
  if (info) info.hidden = false;

  if (files.length === 1) {
    const file = files[0];
    if (filename) filename.textContent = file.name;
    if (filesize) filesize.textContent = formatBytes(file.size);
    if (badge) {
      const parts = file.name.split(".");
      const ext = parts.length > 1 ? parts.pop().toUpperCase() : "FILE";
      badge.textContent = ext;
    }
  } else {
    const totalBytes = Array.from(files).reduce((acc, f) => acc + f.size, 0);
    if (filename) filename.textContent = `${files.length} files selected`;
    if (filesize) filesize.textContent = formatBytes(totalBytes);
    if (badge) badge.textContent = `${files.length} FILES`;
  }
}

document.querySelectorAll(".drop-zone").forEach((zone) => {
  const input = zone.querySelector(".drop-zone-input");
  if (!input) return;

  input.addEventListener("change", () => {
    updateDropZone(zone, input.files);
  });

  zone.addEventListener("dragenter", (e) => {
    e.preventDefault();
    zone.classList.add("drag-over");
  });

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("drag-over");
  });

  zone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    if (!zone.contains(e.relatedTarget)) {
      zone.classList.remove("drag-over");
    }
  });

  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
});

document.querySelectorAll(".operation-card").forEach((card) => {
  card.addEventListener("dragenter", (e) => {
    e.preventDefault();
    card.classList.add("card-drag-over");
  });

  card.addEventListener("dragover", (e) => {
    e.preventDefault();
    card.classList.add("card-drag-over");
  });

  card.addEventListener("dragleave", (e) => {
    e.preventDefault();
    if (!card.contains(e.relatedTarget)) {
      card.classList.remove("card-drag-over");
    }
  });

  card.addEventListener("drop", (e) => {
    card.classList.remove("card-drag-over");
    if (e.target.closest(".drop-zone")) {
      return;
    }
    e.preventDefault();
    const input = card.querySelector(".drop-zone-input") || card.querySelector('input[type="file"]');
    if (input && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
});

window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
*/

