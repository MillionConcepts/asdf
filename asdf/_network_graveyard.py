class DriveBot(GoogleDrive):
    """
    convenience wrapper adding abstract pseudo-filesystem operations to
    a pydrive2 GoogleDrive object
    """

    # TODO: maybe fold in silencio after some more work
    def mkdir(self, folder_name, parent_id):
        gdrive_folder = self.CreateFile(
            {
                "title": folder_name,
                "parents": [{"id": parent_id}],
                "mimeType": "application/vnd.google-apps.folder",
            }
        )
        gdrive_folder.Upload()
        folder_id = gdrive_folder["id"]
        return folder_id

    def cp(self, source_path, target_folder):
        upload = self.CreateFile(
            {
                "title": Path(source_path).name,
                "parents": [{"id": target_folder}],
            }
        )
        upload.SetContentFile(source_path)
        upload.Upload()

    def ls(self, folder_id, trashed=False):
        filelist = self.ListFile(
            {"q": f"'{folder_id}' in parents and trashed={trashed}"}
        ).GetList()
        return filelist

    def get_checksums(self, folder_id, file_list=None):
        if file_list is None:
            file_list = self.ls(folder_id)
        return {
            file.get("title"): file.get("md5Checksum") for file in file_list
        }

    def cd(self, folder_name, parent_id):
        root_filelist = self.ls(parent_id)
        folder_list = [
            file for file in root_filelist
            if (
                (file["title"] == folder_name)
                and (file['explicitlyTrashed'] is False)
            )
        ]
        if len(folder_list) > 0:
            folder_id = folder_list[0]["id"]
        else:
            folder_id = self.mkdir(folder_name, parent_id)
        return folder_id
