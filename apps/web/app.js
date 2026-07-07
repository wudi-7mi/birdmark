(function () {
  const {
    Alert,
    Avatar,
    Badge,
    Button,
    Divider,
    Drawer,
    Empty,
    Image,
    Input,
    InputNumber,
    List,
    Modal,
    Progress,
    Segmented,
    Space,
    Spin,
    Statistic,
    Tag,
    Tooltip,
    Typography,
    Upload,
    message,
  } = antd;

  const iconSet = window.icons || {};
  const {
    AppstoreOutlined,
    BookOutlined,
    CameraOutlined,
    CheckCircleOutlined,
    CloudUploadOutlined,
    DeleteOutlined,
    FolderOpenOutlined,
    LoginOutlined,
    LogoutOutlined,
    ReloadOutlined,
    UserOutlined,
  } = iconSet;

  const h = React.createElement;
  const { Text, Title } = Typography;
  const { useCallback, useEffect, useMemo, useState } = React;
  const TOKEN_KEY = "birdmark_access_token";

  function icon(IconComponent) {
    return IconComponent ? h(IconComponent) : null;
  }

  function App() {
    const [token, setToken] = useState(function () {
      return localStorage.getItem(TOKEN_KEY) || "";
    });
    const [user, setUser] = useState(null);
    const [booting, setBooting] = useState(Boolean(token));
    const [active, setActive] = useState("feed");
    const [loading, setLoading] = useState({});
    const [feed, setFeed] = useState({ results: [], limit: 50, offset: 0 });
    const [collection, setCollection] = useState([]);
    const [myPhotos, setMyPhotos] = useState({ results: [], limit: 100, offset: 0 });
    const [batches, setBatches] = useState({ results: [], limit: 50, offset: 0 });
    const [selectedDetail, setSelectedDetail] = useState(null);
    const [detailOpen, setDetailOpen] = useState(false);
    const [selectedBatch, setSelectedBatch] = useState(null);

    const setLoadingKey = useCallback(function (key, value) {
      setLoading(function (current) {
        return Object.assign({}, current, { [key]: value });
      });
    }, []);

    const clearSession = useCallback(function () {
      localStorage.removeItem(TOKEN_KEY);
      setToken("");
      setUser(null);
      setFeed({ results: [], limit: 50, offset: 0 });
      setCollection([]);
      setMyPhotos({ results: [], limit: 100, offset: 0 });
      setBatches({ results: [], limit: 50, offset: 0 });
      setSelectedDetail(null);
      setDetailOpen(false);
    }, []);

    const request = useCallback(
      async function (path, options) {
        const nextOptions = options || {};
        const headers = Object.assign({}, nextOptions.headers || {});
        if (token) headers.Authorization = `Bearer ${token}`;

        let body = nextOptions.body;
        if (nextOptions.json !== undefined) {
          headers["Content-Type"] = "application/json";
          body = JSON.stringify(nextOptions.json);
        }

        const response = await fetch(path, {
          method: nextOptions.method || "GET",
          headers,
          body,
        });
        const contentType = response.headers.get("content-type") || "";
        const data = contentType.includes("application/json")
          ? await response.json().catch(function () {
              return {};
            })
          : await response.text();

        if (response.status === 401) {
          clearSession();
        }
        if (!response.ok) {
          const error = new Error(formatApiError(data, response.status));
          error.status = response.status;
          error.data = data;
          throw error;
        }
        return data;
      },
      [clearSession, token],
    );

    useEffect(
      function () {
        if (!token) {
          setBooting(false);
          return;
        }
        let cancelled = false;
        setBooting(true);
        request("/auth/me")
          .then(function (data) {
            if (!cancelled) setUser(data.user);
          })
          .catch(function () {
            if (!cancelled) clearSession();
          })
          .finally(function () {
            if (!cancelled) setBooting(false);
          });
        return function cleanup() {
          cancelled = true;
        };
      },
      [clearSession, request, token],
    );

    const loadFeed = useCallback(
      async function () {
        setLoadingKey("feed", true);
        try {
          setFeed(await request("/photos?limit=50&offset=0"));
        } catch (err) {
          message.error(err.message);
        } finally {
          setLoadingKey("feed", false);
        }
      },
      [request, setLoadingKey],
    );

    const loadCollection = useCallback(
      async function () {
        setLoadingKey("collection", true);
        try {
          const data = await request("/me/collection");
          setCollection(data.results || []);
        } catch (err) {
          message.error(err.message);
        } finally {
          setLoadingKey("collection", false);
        }
      },
      [request, setLoadingKey],
    );

    const loadMyPhotos = useCallback(
      async function () {
        setLoadingKey("myPhotos", true);
        try {
          setMyPhotos(await request("/me/photos?limit=100&offset=0"));
        } catch (err) {
          message.error(err.message);
        } finally {
          setLoadingKey("myPhotos", false);
        }
      },
      [request, setLoadingKey],
    );

    const loadBatches = useCallback(
      async function () {
        setLoadingKey("batches", true);
        try {
          setBatches(await request("/me/import-batches?limit=50&offset=0"));
        } catch (err) {
          message.error(err.message);
        } finally {
          setLoadingKey("batches", false);
        }
      },
      [request, setLoadingKey],
    );

    useEffect(
      function () {
        if (!user) return;
        if (active === "feed") loadFeed();
        if (active === "collection") loadCollection();
        if (active === "mine") loadMyPhotos();
        if (active === "imports") loadBatches();
      },
      [active, loadBatches, loadCollection, loadFeed, loadMyPhotos, user],
    );

    async function openPhoto(photoId) {
      setLoadingKey("detail", true);
      try {
        const data = await request(`/photos/${photoId}`);
        setSelectedDetail(data);
        setDetailOpen(true);
      } catch (err) {
        message.error(err.message);
      } finally {
        setLoadingKey("detail", false);
      }
    }

    async function refreshDetail() {
      if (!selectedDetail || !selectedDetail.photo) return;
      const data = await request(`/photos/${selectedDetail.photo.id}`);
      setSelectedDetail(data);
    }

    async function refreshAll() {
      if (active === "feed") await loadFeed();
      if (active === "collection") await loadCollection();
      if (active === "mine") await loadMyPhotos();
      if (active === "imports") await loadBatches();
    }

    async function logout() {
      try {
        if (token) await request("/auth/logout", { method: "POST" });
      } catch (_) {
        // Local logout should still succeed when the session is already invalid.
      }
      clearSession();
    }

    if (booting) {
      return h("div", { className: "center-page" }, h(Spin, { size: "large" }));
    }

    if (!token || !user) {
      return h(AuthScreen, {
        onAuthed: function (data) {
          localStorage.setItem(TOKEN_KEY, data.access_token);
          setToken(data.access_token);
          setUser(data.user);
          setActive("feed");
        },
      });
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
          h("div", { className: "brand-mark" }, icon(CameraOutlined)),
          h(
            "div",
            { className: "brand-copy" },
            h("h1", null, "Birdmark"),
            h("span", null, "鸟类识别相册"),
          ),
        ),
        h(
          "div",
          { className: "topbar-actions" },
          h(Segmented, {
            className: "main-nav",
            value: active,
            onChange: setActive,
            options: [
              { label: "共享", value: "feed", icon: icon(AppstoreOutlined) },
              { label: "上传", value: "upload", icon: icon(CloudUploadOutlined) },
              { label: "图鉴", value: "collection", icon: icon(BookOutlined) },
              { label: "我的", value: "mine", icon: icon(UserOutlined) },
              { label: "批量", value: "imports", icon: icon(FolderOpenOutlined) },
            ],
          }),
          h(
            "div",
            { className: "user-pill" },
            h(Avatar, { size: 28, icon: icon(UserOutlined) }),
            h("span", null, user.display_name || user.username),
          ),
          h(
            Tooltip,
            { title: "退出登录" },
            h(Button, { icon: icon(LogoutOutlined), onClick: logout }),
          ),
        ),
      ),
      h(
        "main",
        { className: "page" },
        active === "feed" &&
          h(FeedView, {
            data: feed,
            loading: loading.feed,
            onRefresh: loadFeed,
            onOpenPhoto: openPhoto,
          }),
        active === "upload" &&
          h(UploadView, {
            request,
            onOpenDetail: function (detail) {
              setSelectedDetail(detail);
              setDetailOpen(true);
            },
            onRefreshFeed: loadFeed,
          }),
        active === "collection" &&
          h(CollectionView, {
            items: collection,
            loading: loading.collection,
            onRefresh: loadCollection,
          }),
        active === "mine" &&
          h(MyView, {
            user,
            data: myPhotos,
            loading: loading.myPhotos,
            request,
            onRefresh: loadMyPhotos,
            onOpenPhoto: openPhoto,
          }),
        active === "imports" &&
          h(ImportView, {
            data: batches,
            loading: loading.batches,
            request,
            selectedBatch,
            setSelectedBatch,
            onRefresh: loadBatches,
          }),
      ),
      h(PhotoDetailDrawer, {
        detail: selectedDetail,
        open: detailOpen,
        loading: loading.detail,
        currentUser: user,
        request,
        onClose: function () {
          setDetailOpen(false);
        },
        onChanged: async function () {
          await refreshDetail();
          await refreshAll();
        },
      }),
    );
  }

  function AuthScreen(props) {
    const [mode, setMode] = useState("login");
    const [loading, setLoading] = useState(false);
    const [form, setForm] = useState({
      identifier: "",
      email: "",
      username: "",
      display_name: "",
      password: "",
    });

    function update(key, value) {
      setForm(function (current) {
        return Object.assign({}, current, { [key]: value });
      });
    }

    async function submit() {
      setLoading(true);
      try {
        const path = mode === "login" ? "/auth/login" : "/auth/register";
        const payload =
          mode === "login"
            ? { identifier: form.identifier, password: form.password }
            : {
                email: form.email,
                username: form.username,
                display_name: form.display_name,
                password: form.password,
              };
        const response = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(function () {
          return {};
        });
        if (!response.ok) throw new Error(formatApiError(data, response.status));
        props.onAuthed(data);
      } catch (err) {
        message.error(err.message);
      } finally {
        setLoading(false);
      }
    }

    return h(
      "div",
      { className: "auth-page" },
      h(
        "section",
        { className: "auth-panel" },
        h(
          "div",
          { className: "auth-brand" },
          h("div", { className: "brand-mark large" }, icon(CameraOutlined)),
          h("div", null, h("h1", null, "Birdmark"), h("span", null, "鸟类识别相册")),
        ),
        h(Segmented, {
          block: true,
          value: mode,
          onChange: setMode,
          options: [
            { label: "登录", value: "login", icon: icon(LoginOutlined) },
            { label: "注册", value: "register", icon: icon(UserOutlined) },
          ],
        }),
        h(
          "div",
          { className: "auth-form" },
          mode === "login"
            ? h(Input, {
                size: "large",
                placeholder: "邮箱或用户名",
                value: form.identifier,
                onChange: function (event) {
                  update("identifier", event.target.value);
                },
                onPressEnter: submit,
              })
            : h(
                React.Fragment,
                null,
                h(Input, {
                  size: "large",
                  placeholder: "邮箱",
                  value: form.email,
                  onChange: function (event) {
                    update("email", event.target.value);
                  },
                }),
                h(Input, {
                  size: "large",
                  placeholder: "用户名",
                  value: form.username,
                  onChange: function (event) {
                    update("username", event.target.value);
                  },
                }),
                h(Input, {
                  size: "large",
                  placeholder: "昵称",
                  value: form.display_name,
                  onChange: function (event) {
                    update("display_name", event.target.value);
                  },
                }),
              ),
          h(Input.Password, {
            size: "large",
            placeholder: "密码",
            value: form.password,
            onChange: function (event) {
              update("password", event.target.value);
            },
            onPressEnter: submit,
          }),
          h(
            Button,
            {
              type: "primary",
              size: "large",
              block: true,
              loading,
              onClick: submit,
            },
            mode === "login" ? "登录" : "注册并进入",
          ),
        ),
      ),
    );
  }

  function FeedView(props) {
    const results = props.data.results || [];
    return h(
      "section",
      { className: "workbench" },
      h(SectionHeader, {
        title: "共享相册",
        extra: h(Button, {
          icon: icon(ReloadOutlined),
          loading: props.loading,
          onClick: props.onRefresh,
        }),
      }),
      props.loading && !results.length
        ? h("div", { className: "center-block" }, h(Spin))
        : results.length
          ? h(
              "div",
              { className: "photo-grid" },
              results.map(function (item) {
                return h(PhotoCard, {
                  key: item.photo.id,
                  item,
                  onOpen: props.onOpenPhoto,
                });
              }),
            )
          : h(Empty, { className: "panel-empty", description: "还没有照片" }),
    );
  }

  function UploadView(props) {
    const [file, setFile] = useState(null);
    const [preview, setPreview] = useState("");
    const [topK, setTopK] = useState(5);
    const [uploading, setUploading] = useState(false);

    useEffect(
      function () {
        return function cleanup() {
          if (preview) URL.revokeObjectURL(preview);
        };
      },
      [preview],
    );

    const uploadProps = useMemo(
      function () {
        return {
          accept: "image/*",
          maxCount: 1,
          showUploadList: false,
          beforeUpload: function (nextFile) {
            if (preview) URL.revokeObjectURL(preview);
            setFile(nextFile);
            setPreview(URL.createObjectURL(nextFile));
            return false;
          },
        };
      },
      [preview],
    );

    async function upload() {
      if (!file) {
        message.warning("请选择图片");
        return;
      }
      setUploading(true);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const detail = await props.request(`/photos?top_k=${topK}`, {
          method: "POST",
          body: formData,
        });
        message.success("上传完成");
        props.onOpenDetail(detail);
        props.onRefreshFeed();
      } catch (err) {
        message.error(err.message);
      } finally {
        setUploading(false);
      }
    }

    return h(
      "section",
      { className: "workbench upload-layout" },
      h(
        "div",
        { className: "upload-panel" },
        h(SectionHeader, { title: "上传识别" }),
        h(
          Upload.Dragger,
          uploadProps,
          h("p", { className: "ant-upload-drag-icon" }, icon(CloudUploadOutlined)),
          h("p", { className: "ant-upload-text" }, "选择或拖入图片"),
          h("p", { className: "ant-upload-hint" }, file ? file.name : "JPG、PNG、WEBP"),
        ),
        h(
          "div",
          { className: "upload-actions" },
          h(
            "label",
            { className: "field-inline" },
            h("span", null, "Top-K"),
            h(InputNumber, {
              min: 1,
              max: 20,
              value: topK,
              onChange: function (value) {
                setTopK(value || 5);
              },
            }),
          ),
          h(
            Button,
            {
              type: "primary",
              icon: icon(CloudUploadOutlined),
              loading: uploading,
              onClick: upload,
            },
            "上传并识别",
          ),
        ),
      ),
      h(
        "div",
        { className: "preview-panel" },
        preview
          ? h("img", { src: preview, alt: "待上传图片" })
          : h(Empty, { description: "未选择图片" }),
      ),
    );
  }

  function CollectionView(props) {
    return h(
      "section",
      { className: "workbench" },
      h(SectionHeader, {
        title: "我的图鉴",
        extra: h(Button, {
          icon: icon(ReloadOutlined),
          loading: props.loading,
          onClick: props.onRefresh,
        }),
      }),
      props.loading && !props.items.length
        ? h("div", { className: "center-block" }, h(Spin))
        : props.items.length
          ? h(
              "div",
              { className: "collection-grid" },
              props.items.map(function (item) {
                return h(
                  "article",
                  { className: "collection-card", key: item.id },
                  imageOrPlaceholder(item.thumb_url || item.crop_url, item.common_name || item.scientific_name),
                  h(
                    "div",
                    { className: "collection-body" },
                    h("h3", null, item.chinese_name || item.common_name || item.scientific_name),
                    item.scientific_name && h(Text, { type: "secondary" }, item.scientific_name),
                    h(
                      "div",
                      { className: "metric-row" },
                      h(Statistic, { title: "观察", value: item.observation_count || 0 }),
                      h(Statistic, { title: "物种", value: item.species_id }),
                    ),
                  ),
                );
              }),
            )
          : h(Empty, { className: "panel-empty", description: "确认鉴定后会出现在这里" }),
    );
  }

  function MyView(props) {
    const rows = props.data.results || [];

    async function deletePhoto(photoId) {
      Modal.confirm({
        title: "删除这张照片？",
        content: "删除后会从共享相册和我的上传中移除。",
        okText: "删除",
        okType: "danger",
        cancelText: "取消",
        onOk: async function () {
          try {
            await props.request(`/photos/${photoId}`, { method: "DELETE" });
            message.success("已删除");
            props.onRefresh();
          } catch (err) {
            message.error(err.message);
          }
        },
      });
    }

    return h(
      "section",
      { className: "workbench mine-layout" },
      h(
        "aside",
        { className: "profile-panel" },
        h(Avatar, { size: 52, icon: icon(UserOutlined) }),
        h("h2", null, props.user.display_name || props.user.username),
        h(Text, { type: "secondary" }, props.user.email),
        h(Divider),
        h("div", { className: "profile-row" }, h("span", null, "用户名"), h("b", null, props.user.username)),
        h("div", { className: "profile-row" }, h("span", null, "角色"), h("b", null, props.user.role || "user")),
      ),
      h(
        "div",
        { className: "uploads-panel" },
        h(SectionHeader, {
          title: "我的上传",
          extra: h(Button, {
            icon: icon(ReloadOutlined),
            loading: props.loading,
            onClick: props.onRefresh,
          }),
        }),
        props.loading && !rows.length
          ? h("div", { className: "center-block" }, h(Spin))
          : rows.length
            ? h(
                "div",
                { className: "upload-list" },
                rows.map(function (photo) {
                  return h(
                    "article",
                    { className: "upload-row", key: photo.id },
                    imageOrPlaceholder(photo.thumb_url || photo.original_url, photo.filename),
                    h(
                      "div",
                      { className: "upload-row-main" },
                      h("h3", null, photo.filename || `照片 #${photo.id}`),
                      h(
                        "div",
                        { className: "tag-line" },
                        h(Tag, { color: photo.status === "ready" ? "green" : "default" }, photo.status),
                        h(Tag, null, formatDate(photo.created_at)),
                      ),
                    ),
                    h(
                      "div",
                      { className: "row-actions" },
                      h(Button, { onClick: function () { props.onOpenPhoto(photo.id); } }, "详情"),
                      h(Button, {
                        danger: true,
                        icon: icon(DeleteOutlined),
                        onClick: function () {
                          deletePhoto(photo.id);
                        },
                      }),
                    ),
                  );
                }),
              )
            : h(Empty, { className: "panel-empty", description: "还没有上传记录" }),
      ),
    );
  }

  function ImportView(props) {
    const [files, setFiles] = useState([]);
    const [creating, setCreating] = useState(false);
    const [topK, setTopK] = useState(5);
    const rows = props.data.results || [];

    const uploadProps = {
      accept: "image/*",
      multiple: true,
      showUploadList: false,
      beforeUpload: function (file) {
        setFiles(function (current) {
          return current.concat(file);
        });
        return false;
      },
    };

    async function createBatch() {
      if (!files.length) {
        message.warning("请选择图片");
        return;
      }
      setCreating(true);
      try {
        const formData = new FormData();
        files.forEach(function (file) {
          formData.append("files", file);
        });
        const data = await props.request(`/import-batches?top_k=${topK}`, {
          method: "POST",
          body: formData,
        });
        props.setSelectedBatch(data);
        setFiles([]);
        await props.onRefresh();
        message.success("批量任务已创建");
      } catch (err) {
        message.error(err.message);
      } finally {
        setCreating(false);
      }
    }

    async function openBatch(batchId) {
      try {
        props.setSelectedBatch(await props.request(`/import-batches/${batchId}`));
      } catch (err) {
        message.error(err.message);
      }
    }

    return h(
      "section",
      { className: "workbench imports-layout" },
      h(
        "div",
        { className: "import-create" },
        h(SectionHeader, { title: "批量导入" }),
        h(
          Upload.Dragger,
          uploadProps,
          h("p", { className: "ant-upload-drag-icon" }, icon(FolderOpenOutlined)),
          h("p", { className: "ant-upload-text" }, "选择多张图片"),
          h("p", { className: "ant-upload-hint" }, files.length ? `${files.length} 张待上传` : "最多 50 张"),
        ),
        h(
          "div",
          { className: "upload-actions" },
          h(
            "label",
            { className: "field-inline" },
            h("span", null, "Top-K"),
            h(InputNumber, {
              min: 1,
              max: 20,
              value: topK,
              onChange: function (value) {
                setTopK(value || 5);
              },
            }),
          ),
          h(Button, { onClick: function () { setFiles([]); } }, "清空"),
          h(Button, { type: "primary", loading: creating, onClick: createBatch }, "创建任务"),
        ),
      ),
      h(
        "div",
        { className: "import-list" },
        h(SectionHeader, {
          title: "任务记录",
          extra: h(Button, {
            icon: icon(ReloadOutlined),
            loading: props.loading,
            onClick: props.onRefresh,
          }),
        }),
        rows.length
          ? h(
              "div",
              { className: "batch-list" },
              rows.map(function (batch) {
                const percent = batch.total_count
                  ? Math.round((batch.processed_count / batch.total_count) * 100)
                  : 0;
                return h(
                  "article",
                  { className: "batch-row", key: batch.id },
                  h(
                    "div",
                    null,
                    h("h3", null, `任务 #${batch.id}`),
                    h(
                      "div",
                      { className: "tag-line" },
                      renderBatchStatus(batch.status),
                      h(Tag, null, formatDate(batch.created_at)),
                    ),
                  ),
                  h(Progress, { percent, size: "small" }),
                  h(
                    "div",
                    { className: "batch-counts" },
                    h("span", null, `成功 ${batch.succeeded_count}`),
                    h("span", null, `失败 ${batch.failed_count}`),
                    h("span", null, `总数 ${batch.total_count}`),
                  ),
                  h(Button, { onClick: function () { openBatch(batch.id); } }, "查看"),
                );
              }),
            )
          : h(Empty, { className: "panel-empty", description: "还没有批量任务" }),
      ),
      props.selectedBatch &&
        h(
          "div",
          { className: "batch-detail" },
          h(SectionHeader, {
            title: `任务 #${props.selectedBatch.batch.id}`,
            extra: h(Button, {
              icon: icon(ReloadOutlined),
              onClick: function () {
                openBatch(props.selectedBatch.batch.id);
              },
            }),
          }),
          h(
            List,
            {
              dataSource: props.selectedBatch.items || [],
              renderItem: function (item) {
                return h(
                  List.Item,
                  null,
                  h(
                    List.Item.Meta,
                    {
                      avatar: item.photo
                        ? h("img", {
                            className: "tiny-thumb",
                            src: item.photo.thumb_url || item.photo.original_url,
                            alt: item.filename,
                          })
                        : h("div", { className: "tiny-thumb empty" }),
                      title: item.filename || `条目 #${item.id}`,
                      description: item.error_message || (item.photo ? `照片 #${item.photo.id}` : ""),
                    },
                  ),
                  renderItemStatus(item.status),
                );
              },
            },
          ),
        ),
    );
  }

  function PhotoDetailDrawer(props) {
    const detail = props.detail;
    const [manualForms, setManualForms] = useState({});
    const [actionLoading, setActionLoading] = useState("");

    useEffect(
      function () {
        setManualForms({});
      },
      [detail && detail.photo && detail.photo.id],
    );

    if (!detail) return null;
    const photo = detail.photo || {};
    const observations = detail.observations || [];
    const canEdit = props.currentUser && Number(photo.user_id) === Number(props.currentUser.id);

    function updateManual(observationId, key, value) {
      setManualForms(function (current) {
        const next = Object.assign({}, current);
        next[observationId] = Object.assign({}, next[observationId] || {}, { [key]: value });
        return next;
      });
    }

    async function runAction(key, fn) {
      setActionLoading(key);
      try {
        await fn();
        await props.onChanged();
        message.success("已更新");
      } catch (err) {
        message.error(err.message);
      } finally {
        setActionLoading("");
      }
    }

    return h(
      Drawer,
      {
        title: photo.filename || `照片 #${photo.id}`,
        width: 760,
        open: props.open,
        onClose: props.onClose,
      },
      props.loading
        ? h("div", { className: "center-block" }, h(Spin))
        : h(
            "div",
            { className: "detail-view" },
            h(
              "div",
              { className: "detail-photo" },
              imageOrPlaceholder(photo.original_url || photo.thumb_url, photo.filename),
            ),
            h(
              "div",
              { className: "detail-meta" },
              h(Tag, null, photo.display_name || photo.username || "未知用户"),
              h(Tag, { color: photo.status === "ready" ? "green" : "default" }, photo.status),
              h(Tag, null, formatDate(photo.created_at)),
            ),
            observations.length
              ? observations.map(function (observation) {
                  const identification = observation.identification || {};
                  const predictions = identification.top_k_results || [];
                  const manual = manualForms[observation.id] || {};
                  return h(
                    "section",
                    { className: "observation-panel", key: observation.id },
                    h(
                      "div",
                      { className: "observation-head" },
                      h("h3", null, `观察 #${observation.id}`),
                      h(
                        "div",
                        { className: "tag-line" },
                        h(Tag, { color: observation.status === "confirmed" ? "green" : "blue" }, observation.status),
                        identification.status && h(Tag, null, identification.status),
                      ),
                    ),
                    h(
                      "div",
                      { className: "observation-grid" },
                      imageOrPlaceholder(observation.crop_url, `观察 #${observation.id}`),
                      h(
                        "div",
                        { className: "prediction-list" },
                        predictions.length
                          ? predictions.map(function (prediction, index) {
                              const name = formatPredictionName(prediction);
                              const score = Math.round((prediction.score || 0) * 1000) / 10;
                              return h(
                                "div",
                                { className: "prediction-row", key: `${observation.id}-${index}` },
                                h(
                                  "div",
                                  { className: "prediction-main" },
                                  h("strong", null, name),
                                  h(Progress, { percent: score, size: "small" }),
                                ),
                                canEdit &&
                                  h(
                                    Button,
                                    {
                                      size: "small",
                                      icon: icon(CheckCircleOutlined),
                                      loading: actionLoading === `confirm-${observation.id}-${index}`,
                                      onClick: function () {
                                        runAction(`confirm-${observation.id}-${index}`, function () {
                                          return props.request(`/observations/${observation.id}/confirm`, {
                                            method: "POST",
                                            json: { prediction_index: index },
                                          });
                                        });
                                      },
                                    },
                                    "确认",
                                  ),
                              );
                            })
                          : h(Empty, { description: "没有建议" }),
                      ),
                    ),
                    canEdit &&
                      h(
                        "div",
                        { className: "manual-box" },
                        h(Input, {
                          placeholder: "学名",
                          value: manual.scientific_name || "",
                          onChange: function (event) {
                            updateManual(observation.id, "scientific_name", event.target.value);
                          },
                        }),
                        h(Input, {
                          placeholder: "英文名",
                          value: manual.common_name || "",
                          onChange: function (event) {
                            updateManual(observation.id, "common_name", event.target.value);
                          },
                        }),
                        h(Input, {
                          placeholder: "中文名",
                          value: manual.chinese_name || "",
                          onChange: function (event) {
                            updateManual(observation.id, "chinese_name", event.target.value);
                          },
                        }),
                        h(
                          Button,
                          {
                            onClick: function () {
                              if (!manual.scientific_name) {
                                message.warning("请填写学名");
                                return;
                              }
                              runAction(`manual-${observation.id}`, function () {
                                return props.request(`/observations/${observation.id}/confirm`, {
                                  method: "POST",
                                  json: manual,
                                });
                              });
                            },
                            loading: actionLoading === `manual-${observation.id}`,
                          },
                          "手动确认",
                        ),
                        h(Button, {
                          onClick: function () {
                            runAction(`unknown-${observation.id}`, function () {
                              return props.request(`/observations/${observation.id}/mark-unknown`, {
                                method: "POST",
                              });
                            });
                          },
                          loading: actionLoading === `unknown-${observation.id}`,
                        }, "未知"),
                        h(Button, {
                          danger: true,
                          onClick: function () {
                            runAction(`reject-${observation.id}`, function () {
                              return props.request(`/observations/${observation.id}/reject`, {
                                method: "POST",
                              });
                            });
                          },
                          loading: actionLoading === `reject-${observation.id}`,
                        }, "误检"),
                      ),
                  );
                })
              : h(Empty, { description: "没有观察记录" }),
          ),
    );
  }

  function PhotoCard(props) {
    const photo = props.item.photo || {};
    const observations = props.item.observations || [];
    const confirmedCount = observations.filter(function (item) {
      return item.status === "confirmed";
    }).length;
    const firstIdentification = observations[0] && observations[0].identification;
    const best = firstIdentification && firstIdentification.top_k_results && firstIdentification.top_k_results[0];

    return h(
      "article",
      { className: "photo-card" },
      h(
        "button",
        {
          className: "photo-button",
          type: "button",
          onClick: function () {
            props.onOpen(photo.id);
          },
        },
        imageOrPlaceholder(photo.thumb_url || photo.original_url, photo.filename),
      ),
      h(
        "div",
        { className: "photo-card-body" },
        h("h3", null, best ? formatPredictionName(best) : photo.filename || `照片 #${photo.id}`),
        h(
          "div",
          { className: "tag-line" },
          h(Tag, null, photo.display_name || photo.username || "未知用户"),
          h(Tag, { color: photo.status === "ready" ? "green" : "default" }, photo.status),
          confirmedCount > 0 && h(Tag, { color: "gold" }, `已确认 ${confirmedCount}`),
        ),
        h(
          "div",
          { className: "card-footer" },
          h(Text, { type: "secondary" }, formatDate(photo.created_at)),
          h(Button, {
            size: "small",
            onClick: function () {
              props.onOpen(photo.id);
            },
          }, "详情"),
        ),
      ),
    );
  }

  function SectionHeader(props) {
    return h(
      "div",
      { className: "section-header" },
      h(Title, { level: 2 }, props.title),
      props.extra || null,
    );
  }

  function imageOrPlaceholder(src, alt) {
    return src
      ? h(Image, {
          src,
          alt: alt || "图片",
          preview: false,
          fallback: "",
        })
      : h(
          "div",
          { className: "image-placeholder" },
          icon(CameraOutlined),
        );
  }

  function renderBatchStatus(status) {
    const color =
      status === "completed"
        ? "green"
        : status === "completed_with_errors"
          ? "orange"
          : status === "failed"
            ? "red"
            : "blue";
    return h(Tag, { color }, status);
  }

  function renderItemStatus(status) {
    const color = status === "completed" ? "green" : status === "failed" ? "red" : "blue";
    return h(Badge, { color, text: status });
  }

  function formatPredictionName(prediction) {
    if (!prediction) return "未知鸟类";
    const common = prediction.common_name;
    const scientific = prediction.species || prediction.scientific_name;
    if (common && scientific) return `${common} / ${scientific}`;
    return common || scientific || "未知鸟类";
  }

  function formatApiError(data, status) {
    if (data && typeof data === "object") {
      if (typeof data.detail === "string") return data.detail;
      if (data.detail && typeof data.detail.error === "string") return data.detail.error;
      if (Array.isArray(data.detail)) return data.detail.map(function (item) { return item.msg || "请求错误"; }).join("；");
    }
    if (typeof data === "string" && data) return data;
    return `请求失败：${status}`;
  }

  function formatDate(value) {
    if (!value) return "";
    if (window.dayjs) return dayjs(value).format("YYYY-MM-DD HH:mm");
    return String(value);
  }

  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
