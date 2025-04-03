from ..base_downloader import BaseModelDownloader, get_model_dirs, get_base_dir
from ..download_utils import DownloadManager
import requests
import os
import shutil


class CivitAIDownloader(BaseModelDownloader):
    base_url = "https://civitai.com/api"

    # Mapping CivitAI model types to ComfyUI folder structure
    MODEL_TYPE_MAPPING = {
        "Checkpoint": "checkpoints",
        "TextualInversion": "embeddings",
        "Hypernetwork": "hypernetworks",
        "AestheticGradient": "style_models",
        "LORA": "loras",
        "Controlnet": "controlnet",
        "Poses": "poses",  # May not exist by default
        "Other": "custom_models",  # Fallback
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_id": ("STRING", {"multiline": False, "default": "360292"}),
                "version_id": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "placeholder": "Leave empty for latest version",
                    },
                ),
                "token_id": (
                    "STRING",
                    {"multiline": False, "default": "API_token_here"},
                ),
                "save_dir": (get_model_dirs(),),
                "download_all": ("BOOLEAN", {"default": False}),
                "create_subdirectory": ("BOOLEAN", {"default": True}),
                "add_version_prefix": ("BOOLEAN", {"default": True}),
                "create_model_links": ("BOOLEAN", {"default": True}),
            },
            "hidden": {"node_id": "UNIQUE_ID"},
        }

    FUNCTION = "download"

    def get_model_details(self, model_id, token_id):
        """Get the model details including type from the CivitAI API"""
        model_details_url = f"{self.base_url}/v1/models/{model_id}"
        response = requests.get(
            model_details_url, headers={"Authorization": f"Bearer {token_id}"}
        )

        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch model details. Status code: {response.status_code}"
            )

        model_details = response.json()
        return model_details

    def get_download_filename_url(self, model_id, version_id, token_id):
        """Find the model filename and URL from the CivitAI API
        If version_id is provided, download that specific version
        Otherwise, download the latest version
        Returns: filename, url, actual_version_id, model_type
        """
        model_details = self.get_model_details(model_id, token_id)
        model_type = model_details.get("type", "Other")
        model_versions = model_details.get("modelVersions", [])

        if not model_versions:
            raise Exception(f"No versions found for model ID {model_id}")

        # If version_id is provided, find that specific version
        if version_id:
            for model_version in model_versions:
                if str(model_version["id"]) == version_id:
                    files = model_version.get("files", [])
                    if not files:
                        raise Exception(f"No files found for version {version_id}")

                    # Get the primary file (usually the first one)
                    filename = files[0]["name"]
                    url = files[0]["downloadUrl"]
                    return filename, url, version_id, model_type

            # If we reach here, the specified version was not found
            raise Exception(f"Version {version_id} not found for model ID {model_id}")

        # If no version_id is provided, use the latest version (first in the list)
        else:
            # Sort versions by creation date (newest first)
            model_versions.sort(key=lambda x: x["createdAt"], reverse=True)
            latest_version = model_versions[0]
            files = latest_version.get("files", [])

            if not files:
                raise Exception(
                    f"No files found for latest version of model ID {model_id}"
                )

            filename = files[0]["name"]
            url = files[0]["downloadUrl"]
            actual_version_id = str(latest_version["id"])
            return filename, url, actual_version_id, model_type

    def get_target_directory(self, model_type, custom_dir=None):
        """Get the appropriate directory path based on model type"""
        if custom_dir:
            return custom_dir

        folder_name = self.MODEL_TYPE_MAPPING.get(model_type, "custom_models")
        target_dir = os.path.join(get_base_dir(), folder_name)

        # Ensure the directory exists
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        return target_dir

    def download(
        self,
        model_id,
        version_id,
        download_all,
        token_id,
        save_dir,
        node_id,
        create_subdirectory=True,
        add_version_prefix=True,
        create_model_links=True,
    ):
        self.node_id = node_id

        if download_all:
            # Get model details including type
            model_details = self.get_model_details(model_id, token_id)
            model_type = model_details.get("type", "Other")
            model_versions = model_details.get("modelVersions", [])

            if not model_versions:
                raise Exception(f"No versions found for model ID {model_id}")

            # Count total files to download for progress tracking
            valid_versions = []

            # First, collect all valid versions with files
            for model_version in model_versions:
                version_id = str(model_version["id"])
                files = model_version.get("files", [])
                if files:
                    valid_versions.append(
                        {
                            "version_id": version_id,
                            "filename": files[0]["name"],
                            "url": files[0]["downloadUrl"],
                        }
                    )

            total_files = len(valid_versions)
            if total_files == 0:
                raise Exception(f"No files found for model ID {model_id}")

            print(
                f"Found {total_files} versions to download for model type: {model_type}"
            )

            # Create a progress tracker wrapper
            class ProgressTracker:
                def __init__(self, parent, total_files):
                    self.parent = parent
                    self.total_files = total_files
                    self.completed_files = 0
                    self.current_file_progress = 0

                def set_progress(self, file_progress_percentage):
                    self.current_file_progress = file_progress_percentage
                    # Calculate overall progress: completed files + current file's fractional progress
                    overall_progress = (
                        self.completed_files / self.total_files * 100
                    ) + (file_progress_percentage / self.total_files)
                    self.parent.set_progress(overall_progress)

                def file_completed(self):
                    self.completed_files += 1
                    self.current_file_progress = 0

            # Create progress tracker
            progress_tracker = ProgressTracker(self, total_files)

            # Get the target directory for model type links
            model_type_dir = (
                self.get_target_directory(model_type) if create_model_links else None
            )

            # Now download each version
            for idx, version_info in enumerate(valid_versions):
                version_id = version_info["version_id"]
                filename = version_info["filename"]
                url = version_info["url"]

                print(
                    f"Processing version {idx+1}/{total_files}: {version_id} - {filename}"
                )

                # Setup save path (always in the save_dir)
                if create_subdirectory:
                    model_subdirectory = f"{model_id}"
                    full_save_dir = os.path.join(save_dir, model_subdirectory)
                    save_path = self.prepare_download_path(full_save_dir, filename)
                else:
                    save_path = self.prepare_download_path(save_dir, filename)

                # Check if file already exists (either original or with version prefix)
                original_file_path = os.path.join(save_path, filename)
                prefixed_filename = (
                    f"{version_id}_{filename}" if add_version_prefix else filename
                )
                prefixed_file_path = os.path.join(save_path, prefixed_filename)

                if os.path.exists(original_file_path) or (
                    add_version_prefix and os.path.exists(prefixed_file_path)
                ):
                    print(f"File already exists, skipping download: {filename}")
                    progress_tracker.file_completed()

                    # Create symlink even for existing files
                    if create_model_links and model_type_dir:
                        final_path = (
                            prefixed_file_path
                            if add_version_prefix
                            else original_file_path
                        )
                        if os.path.exists(final_path):
                            self.create_model_type_symlink(final_path, model_type_dir)

                    continue

                # Download the file
                self.handle_download(
                    DownloadManager.download_with_progress,
                    url=url,
                    save_path=save_path,
                    filename=filename,
                    progress_callback=progress_tracker,
                    params={"token": token_id},
                )

                # Mark this file as completed
                progress_tracker.file_completed()

                # Rename if needed
                final_path = original_file_path
                if add_version_prefix:
                    if os.path.exists(original_file_path):
                        new_filename = f"{version_id}_{filename}"
                        new_file_path = os.path.join(save_path, new_filename)

                        shutil.move(original_file_path, new_file_path)
                        print(f"Renamed file: {original_file_path} -> {new_file_path}")
                        final_path = new_file_path

                # Create symlink to appropriate model type folder if requested
                if create_model_links and model_type_dir and os.path.exists(final_path):
                    self.create_model_type_symlink(final_path, model_type_dir)

            # Ensure progress reaches 100% at the end
            self.set_progress(100)
            return {}
        else:
            # Single version download
            # Get the original filename, download URL, actual version ID, and model type
            filename, url, actual_version_id, model_type = (
                self.get_download_filename_url(model_id, version_id, token_id)
            )

            # Get the target directory for model type links
            model_type_dir = (
                self.get_target_directory(model_type) if create_model_links else None
            )

            # Setup save path (always in the save_dir)
            if create_subdirectory:
                model_subdirectory = f"{model_id}"
                full_save_dir = os.path.join(save_dir, model_subdirectory)
                save_path = self.prepare_download_path(full_save_dir, filename)
            else:
                save_path = self.prepare_download_path(save_dir, filename)

            # Check if file already exists (either original or with version prefix)
            original_file_path = os.path.join(save_path, filename)
            prefixed_filename = (
                f"{actual_version_id}_{filename}"
                if add_version_prefix and actual_version_id
                else None
            )
            prefixed_file_path = (
                os.path.join(save_path, prefixed_filename)
                if prefixed_filename
                else None
            )

            if os.path.exists(original_file_path) or (
                prefixed_file_path and os.path.exists(prefixed_file_path)
            ):
                print(f"File already exists, skipping download: {filename}")

                # Create symlink even for existing files
                if create_model_links and model_type_dir:
                    # Check which path actually exists
                    if prefixed_file_path and os.path.exists(prefixed_file_path):
                        self.create_model_type_symlink(
                            prefixed_file_path, model_type_dir
                        )
                    elif os.path.exists(original_file_path):
                        self.create_model_type_symlink(
                            original_file_path, model_type_dir
                        )

                return {}

            print(f"Downloading model type: {model_type} to {save_path}")

            # Download the file with its original name
            result = self.handle_download(
                DownloadManager.download_with_progress,
                url=url,
                save_path=save_path,
                filename=filename,
                progress_callback=self,
                params={"token": token_id},
            )

            # After download, optionally rename the file to include the version_id prefix
            final_path = original_file_path
            if add_version_prefix:
                if os.path.exists(original_file_path):
                    # Use the actual version ID (either provided or fetched from latest)
                    version_prefix = actual_version_id or version_id
                    if version_prefix:
                        new_filename = f"{version_prefix}_{filename}"
                        new_file_path = os.path.join(save_path, new_filename)

                        shutil.move(original_file_path, new_file_path)
                        print(f"Renamed file: {original_file_path} -> {new_file_path}")
                        final_path = new_file_path

            # Create symlink to appropriate model type folder if requested
            if create_model_links and model_type_dir and os.path.exists(final_path):
                self.create_model_type_symlink(final_path, model_type_dir)

            return result

    def create_model_type_symlink(self, source_file_path, target_dir):
        """Create a symlink in the appropriate model type folder"""
        if not os.path.exists(source_file_path):
            print(f"Source file not found, cannot create symlink: {source_file_path}")
            return

        # Create target directory if it doesn't exist
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        # Determine target path
        target_filename = os.path.basename(source_file_path)
        target_path = os.path.join(target_dir, target_filename)

        # Check if target already exists
        if os.path.exists(target_path) or os.path.islink(target_path):
            print(f"Target already exists, not creating symlink: {target_path}")
            return

        # Create symlink
        try:
            os.symlink(source_file_path, target_path)
            print(f"Created symlink: {source_file_path} -> {target_path}")
        except Exception as e:
            print(f"Error creating symlink: {str(e)}")
            # If symlink fails, try to copy the file
            try:
                shutil.copy2(source_file_path, target_path)
                print(
                    f"Symlink failed, copied file instead: {source_file_path} -> {target_path}"
                )
            except Exception as copy_error:
                print(f"Error copying file: {str(copy_error)}")
