import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "CivitAI Downloader",
    async setup() {
        // Find the original node definition
        const origNode = LiteGraph.registered_node_types["CivitAI Downloader"];
        if (!origNode) {
            console.error("Original node not found: CivitAI Downloader");
            return;
        }

        // Add handler for widget changes
        const origOnWidgetChanged = origNode.prototype.onWidgetChanged;
        origNode.prototype.onWidgetChanged = function (name, value) {
            // Call original onWidgetChanged if it exists
            if (origOnWidgetChanged) {
                origOnWidgetChanged.call(this, name, value);
            }

            // If "download_all" widget changes, update version_id widget state
            if (name === "download_all") {
                updateWidgetStates(this);
            }
        };

        // Override the onNodeCreated method to set initial widget states
        const origOnNodeCreated = origNode.prototype.onNodeCreated;
        origNode.prototype.onNodeCreated = function () {
            if (origOnNodeCreated) {
                origOnNodeCreated.call(this);
            }

            // Set initial widget states after node is created
            setTimeout(() => updateWidgetStates(this), 100);
        };

        function updateWidgetStates(node) {
            // Find the widgets
            const downloadAllWidget = node.widgets.find(w => w.name === "download_all");
            const versionIdWidget = node.widgets.find(w => w.name === "version_id");

            if (downloadAllWidget && versionIdWidget) {
                // If download_all is checked, disable version_id
                versionIdWidget.disabled = downloadAllWidget.value;

                if (downloadAllWidget.value) {
                    // Store previous value if needed
                    if (!versionIdWidget._previousValue) {
                        versionIdWidget._previousValue = versionIdWidget.value;
                    }
                    versionIdWidget.value = "Downloading all versions";
                } else if (versionIdWidget._previousValue !== undefined) {
                    // Restore previous value
                    versionIdWidget.value = versionIdWidget._previousValue;
                    delete versionIdWidget._previousValue;
                }

                node.setDirtyCanvas(true);
            }
        }
    }
});