(function () {
  const {
    Alert,
    Button,
    Empty,
    Progress,
    Segmented,
    Slider,
    Spin,
    Tag,
    Tooltip,
    Typography,
    Upload,
    message,
  } = antd;
  const iconSet = window.icons || {};
  const {
    AimOutlined,
    CloudUploadOutlined,
    ReloadOutlined,
    ScissorOutlined,
  } = iconSet;

  const h = React.createElement;
  const { useEffect, useMemo, useRef, useState } = React;
  const { Text } = Typography;

  function App() {
    const [file, setFile] = useState(null);
    const [imageUrl, setImageUrl] = useState("");
    const [mode, setMode] = useState("auto");
    const [topK, setTopK] = useState(5);
    const [loading, setLoading] = useState(false);
    const [response, setResponse] = useState(null);
    const [error, setError] = useState("");
    const imageRef = useRef(null);
    const cropperRef = useRef(null);

    const fileName = file ? file.name : "No image selected";
    const resultCount = response ? response.crop_count : 0;

    useEffect(() => {
      return function cleanup() {
        if (imageUrl) URL.revokeObjectURL(imageUrl);
        destroyCropper(cropperRef);
      };
    }, [imageUrl]);

    useEffect(() => {
      destroyCropper(cropperRef);
      if (mode !== "manual" || !imageRef.current || !imageUrl) return;
      cropperRef.current = new Cropper(imageRef.current, {
        viewMode: 1,
        dragMode: "crop",
        autoCrop: true,
        autoCropArea: 0.35,
        responsive: true,
        background: false,
        movable: false,
        rotatable: false,
        scalable: false,
        zoomable: true,
      });
    }, [mode, imageUrl]);

    const uploadProps = useMemo(
      function () {
        return {
          accept: "image/*",
          maxCount: 1,
          showUploadList: false,
          beforeUpload: function (nextFile) {
            const nextUrl = URL.createObjectURL(nextFile);
            if (imageUrl) URL.revokeObjectURL(imageUrl);
            setFile(nextFile);
            setImageUrl(nextUrl);
            setResponse(null);
            setError("");
            return false;
          },
        };
      },
      [imageUrl],
    );

    async function runAuto() {
      if (!file) {
        message.warning("Choose an image first.");
        return;
      }
      setLoading(true);
      setError("");
      try {
        const formData = new FormData();
        formData.append("file", file);
        const data = await postForm(`/analyze?top_k=${topK}`, formData);
        setResponse(data);
      } catch (err) {
        setError(err.message || "Analyze failed.");
      } finally {
        setLoading(false);
      }
    }

    async function runManual() {
      if (!file) {
        message.warning("Choose an image first.");
        return;
      }
      if (!cropperRef.current) {
        message.warning("Draw a box around one bird.");
        return;
      }

      const data = cropperRef.current.getData(true);
      if (data.width < 5 || data.height < 5) {
        message.warning("Selection is too small.");
        return;
      }

      setLoading(true);
      setError("");
      try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("x1", data.x);
        formData.append("y1", data.y);
        formData.append("x2", data.x + data.width);
        formData.append("y2", data.y + data.height);
        const result = await postForm(`/recognize-box?top_k=${topK}`, formData);
        setResponse(result);
      } catch (err) {
        setError(err.message || "Recognition failed.");
      } finally {
        setLoading(false);
      }
    }

    function reset() {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
      destroyCropper(cropperRef);
      setFile(null);
      setImageUrl("");
      setResponse(null);
      setError("");
    }

    return h(
      "div",
      { className: "app-shell" },
      h(
        "header",
        { className: "topbar" },
        h(
          "div",
          { className: "brand" },
          h("h1", { className: "brand-title" }, "Birdmark"),
          h(
            "div",
            { className: "brand-subtitle" },
            "Upload an image, detect birds automatically, or select one bird manually.",
          ),
        ),
        h(
          "div",
          { className: "timing-line" },
          response &&
            h(Tag, { color: "green" }, `${resultCount} crop${resultCount === 1 ? "" : "s"}`),
          response &&
            h(Tag, null, `Total ${formatSeconds(response.timing.total_seconds)}`),
          response && response.device_name && h(Tag, null, response.device_name),
        ),
      ),
      h(
        "main",
        { className: "main-grid" },
        h(
          "section",
          { className: "panel" },
          h(
            "div",
            { className: "panel-header" },
            h("h2", { className: "panel-title" }, "Image"),
            h(
              Tooltip,
              { title: "Clear image and results" },
              h(Button, { icon: h(ReloadOutlined), onClick: reset }),
            ),
          ),
          h(
            "div",
            { className: "panel-body" },
            h(
              Upload.Dragger,
              uploadProps,
              h("p", { className: "ant-upload-drag-icon" }, h(CloudUploadOutlined)),
              h("p", { className: "ant-upload-text" }, "Click or drag an image here"),
              h("p", { className: "ant-upload-hint" }, fileName),
            ),
            h(
              "div",
              { className: "control-row" },
              h(Segmented, {
                value: mode,
                onChange: setMode,
                options: [
                  { label: "Auto", value: "auto", icon: h(AimOutlined) },
                  { label: "Manual", value: "manual", icon: h(ScissorOutlined) },
                ],
              }),
              h(
                "div",
                { className: "topk-control" },
                h(Text, { type: "secondary" }, `Top ${topK}`),
                h(Slider, {
                  min: 1,
                  max: 10,
                  value: topK,
                  onChange: setTopK,
                  tooltip: { formatter: function (value) { return `Top ${value}`; } },
                }),
              ),
              h(Button, {
                type: "primary",
                icon: mode === "auto" ? h(AimOutlined) : h(ScissorOutlined),
                loading,
                disabled: !file,
                onClick: mode === "auto" ? runAuto : runManual,
              }, mode === "auto" ? "Auto analyze" : "Recognize selection"),
            ),
            mode === "manual" &&
              h(
                "div",
                { className: "manual-note" },
                "Manual mode sends exactly one selected box for recognition.",
              ),
            h(
              "div",
              { className: "preview-frame" },
              imageUrl
                ? h("img", {
                    ref: imageRef,
                    src: imageUrl,
                    alt: "Selected upload",
                    onLoad: function () {
                      if (mode === "manual") {
                        destroyCropper(cropperRef);
                        cropperRef.current = new Cropper(imageRef.current, {
                          viewMode: 1,
                          dragMode: "crop",
                          autoCrop: true,
                          autoCropArea: 0.35,
                          responsive: true,
                          background: false,
                          movable: false,
                          rotatable: false,
                          scalable: false,
                          zoomable: true,
                        });
                      }
                    },
                  })
                : h(Empty, { description: "No image loaded" }),
            ),
          ),
        ),
        h(
          "section",
          { className: "panel" },
          h(
            "div",
            { className: "panel-header" },
            h("h2", { className: "panel-title" }, "Birds"),
            response &&
              h(
                "div",
                { className: "timing-line" },
                h("span", null, `Detect ${formatSeconds(response.timing.detect_seconds)}`),
                h("span", null, `Recognize ${formatSeconds(response.timing.recognize_seconds)}`),
              ),
          ),
          h(
            "div",
            { className: "panel-body" },
            error && h(Alert, { type: "error", message: error, showIcon: true }),
            loading && h("div", { className: "empty-state" }, h(Spin, { size: "large" })),
            !loading && !response && !error && h(Empty, { className: "empty-state", description: "Results will appear here" }),
            !loading && response && response.results.length === 0 &&
              h(Empty, { className: "empty-state", description: "No birds found" }),
            !loading && response && response.results.length > 0 &&
              h(
                "div",
                { className: "result-list" },
                response.results.map(function (item) {
                  return h(ResultItem, { key: item.index, item });
                }),
              ),
          ),
        ),
      ),
    );
  }

  function ResultItem(props) {
    const item = props.item;
    const predictions = item.predictions || [];
    const best = predictions[0] || {};
    const title = best.common_name || best.species || "Unknown bird";
    const subtitle = best.common_name && best.species ? best.species : best.common_name || "";
    const imageSrc = outputUrl(item.crop_path);
    const source = item.source || (item.detection_confidence === null ? "manual" : "detector");

    return h(
      "article",
      { className: "result-item" },
      imageSrc
        ? h("img", { className: "result-image", src: imageSrc, alt: title })
        : h("div", { className: "result-image" }),
      h(
        "div",
        null,
        h("h3", { className: "species-title" }, title),
        subtitle && h(Text, { type: "secondary" }, subtitle),
        h(
          "div",
          { className: "result-meta" },
          h(Tag, null, `Box ${formatBox(item.box)}`),
          renderSourceTag(source, item.detection_confidence),
        ),
        h(
          "div",
          null,
          predictions.map(function (prediction, index) {
            const name = prediction.common_name
              ? `${prediction.common_name} (${prediction.species})`
              : prediction.species || "Unknown";
            return h(
              "div",
              { className: "prediction-row", key: `${name}-${index}` },
              h("div", { className: "prediction-name", title: name }, name),
              h(Progress, {
                percent: Math.round((prediction.score || 0) * 1000) / 10,
                size: "small",
                status: "normal",
              }),
            );
          }),
        ),
      ),
    );
  }

  function renderSourceTag(source, confidence) {
    if (source === "manual") return h(Tag, { color: "blue" }, "Manual");
    if (source === "full_image") return h(Tag, { color: "orange" }, "Full image");
    if (typeof confidence === "number") {
      return h(Tag, { color: "green" }, `Detect ${(confidence * 100).toFixed(1)}%`);
    }
    return h(Tag, null, "Auto");
  }

  async function postForm(url, formData) {
    const response = await fetch(url, {
      method: "POST",
      body: formData,
    });
    const data = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      throw new Error(data.detail || `Request failed with ${response.status}`);
    }
    return data;
  }

  function destroyCropper(ref) {
    if (ref.current) {
      ref.current.destroy();
      ref.current = null;
    }
  }

  function outputUrl(path) {
    if (!path) return "";
    const normalized = path.replace(/\\/g, "/").replace(/^res\//, "");
    return `/outputs/${normalized.split("/").map(encodeURIComponent).join("/")}`;
  }

  function formatSeconds(seconds) {
    if (typeof seconds !== "number") return "0.00s";
    return `${seconds.toFixed(2)}s`;
  }

  function formatBox(box) {
    if (!Array.isArray(box)) return "";
    return box.map(function (value) {
      return Math.round(value);
    }).join(", ");
  }

  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
