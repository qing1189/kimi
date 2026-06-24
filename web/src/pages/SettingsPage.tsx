import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

interface Settings {
  auto_delete_chat: "disabled" | "on_completion" | "always";
  version: number;
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const response = await fetch("/api/settings", {
        credentials: "include",
      });

      if (response.status === 401) {
        navigate("/admin");
        return;
      }

      if (!response.ok) {
        throw new Error("Failed to load settings");
      }

      const data = await response.json();
      setSettings(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = async () => {
    if (!settings) return;

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify(settings),
      });

      if (response.status === 401) {
        navigate("/admin");
        return;
      }

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || "Failed to save settings");
      }

      const data = await response.json();
      setSettings(data.settings);
      setSuccess("设置已保存");
      setTimeout(() => setSuccess(""), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FAF9F6] p-6">
        <div className="max-w-4xl mx-auto">
          <div className="animate-pulse">
            <div className="h-8 bg-gray-200 rounded w-1/4 mb-6"></div>
            <div className="bg-white rounded-lg p-6">
              <div className="h-4 bg-gray-200 rounded w-3/4 mb-4"></div>
              <div className="h-4 bg-gray-200 rounded w-1/2"></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="min-h-screen bg-[#FAF9F6] p-6">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700">无法加载设置</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FAF9F6] p-6">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-semibold mb-6 text-gray-800">系统设置</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <p className="text-red-700">{error}</p>
          </div>
        )}

        {success && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
            <p className="text-green-700">{success}</p>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-sm">
          <div className="p-6 border-b border-gray-100">
            <h2 className="text-lg font-medium text-gray-800 mb-2">
              会话管理
            </h2>
            <p className="text-sm text-gray-500">
              配置对话完成后是否自动删除 Kimi 官网的历史记录
            </p>
          </div>

          <div className="p-6">
            <div className="space-y-4">
              <label className="flex items-start space-x-3 cursor-pointer">
                <input
                  type="radio"
                  name="auto_delete_chat"
                  value="disabled"
                  checked={settings.auto_delete_chat === "disabled"}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      auto_delete_chat: e.target.value as any,
                    })
                  }
                  className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-800">不删除（默认）</div>
                  <div className="text-sm text-gray-500">
                    保留所有会话记录在 Kimi 官网，便于审计和回溯
                  </div>
                </div>
              </label>

              <label className="flex items-start space-x-3 cursor-pointer">
                <input
                  type="radio"
                  name="auto_delete_chat"
                  value="on_completion"
                  checked={settings.auto_delete_chat === "on_completion"}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      auto_delete_chat: e.target.value as any,
                    })
                  }
                  className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-800">
                    对话完成后删除
                    <span className="ml-2 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                      推荐
                    </span>
                  </div>
                  <div className="text-sm text-gray-500">
                    每次对话成功完成后自动删除，防止历史记录积累
                  </div>
                </div>
              </label>

              <label className="flex items-start space-x-3 cursor-pointer">
                <input
                  type="radio"
                  name="auto_delete_chat"
                  value="always"
                  checked={settings.auto_delete_chat === "always"}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      auto_delete_chat: e.target.value as any,
                    })
                  }
                  className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-800">始终删除</div>
                  <div className="text-sm text-gray-500">
                    包括错误情况也删除，最大程度保护隐私
                  </div>
                </div>
              </label>
            </div>

            <div className="mt-6 p-4 bg-blue-50 rounded-lg">
              <div className="flex items-start space-x-2">
                <svg
                  className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                    clipRule="evenodd"
                  />
                </svg>
                <div className="text-sm text-blue-800">
                  <p className="font-medium mb-1">说明</p>
                  <ul className="list-disc list-inside space-y-1 text-blue-700">
                    <li>删除的是 Kimi 官网（kimi.com）的历史记录</li>
                    <li>本地请求日志不受影响，仍可在「请求日志」页面查看</li>
                    <li>删除操作失败不会影响正常响应</li>
                    <li>设置立即生效，无需重启服务</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          <div className="p-6 border-t border-gray-100 flex justify-end">
            <button
              onClick={saveSettings}
              disabled={saving}
              className={`px-6 py-2 rounded-lg font-medium transition-colors ${
                saving
                  ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                  : "bg-blue-600 text-white hover:bg-blue-700"
              }`}
            >
              {saving ? "保存中..." : "保存设置"}
            </button>
          </div>
        </div>

        <div className="mt-6 bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-base font-medium text-gray-800 mb-3">
            相关文档
          </h3>
          <ul className="space-y-2 text-sm">
            <li>
              <a
                href="https://github.com/qing1189/kimi/blob/main/docs/AUTO_DELETE_CHAT.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-700 hover:underline"
              >
                📖 自动删除会话功能文档
              </a>
            </li>
            <li>
              <a
                href="https://www.kimi.com/chat/history"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-700 hover:underline"
              >
                🔗 查看 Kimi 官网历史记录
              </a>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
