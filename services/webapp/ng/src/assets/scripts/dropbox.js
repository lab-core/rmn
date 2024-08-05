
options = {

    // Required. Called when a user selects an item in the Chooser.
    success: function (files) {
        document.getElementById("files-dropbox-input").setAttribute("value", files[0].link)
        document.getElementById("files-upload-label").setAttribute("value", files[0].name)
        document.getElementById("files-upload-label").innerHTML = files[0].name
        document.getElementById("number-page-container").style.display = (files[0].name.endsWith('.zip')) ? 'none' : 'block'
    },

    // Optional. Called when the user closes the dialog without selecting a file
    // and does not include any parameters.
    cancel: function () {

    },

    // Optional. "preview" (default) is a preview link to the document for sharing,
    // "direct" is an expiring link to download the contents of the file. For more
    // information about link types, see Link types below.
    linkType: "direct", // or "direct"

    // Optional. A value of false (default) limits selection to a single file, while
    // true enables multiple file selection.
    multiselect: false, // or true

    // Optional. This is a list of file extensions. If specified, the user will
    // only be able to select files with these extensions. You may also specify
    // file types, such as "video" or "images" in the list. For more information,
    // see File types below. By default, all extensions are allowed.
    extensions: ['.pdf', '.zip'],

    // Optional. A value of false (default) limits selection to files,
    // while true allows the user to select both folders and files.
    // You cannot specify `linkType: "direct"` when using `folderselect: true`.
    folderselect: false, // or true
};

optionsCSV = {

    // Required. Called when a user selects an item in the Chooser.
    success: function (files) {
        document.getElementById("csv-dropbox-input").setAttribute("value", files[0].link)
        document.getElementById("csv-upload-label").setAttribute("value", files[0].name)
        document.getElementById("csv-upload-label").innerHTML = files[0].name
    },

    // Optional. Called when the user closes the dialog without selecting a file
    // and does not include any parameters.
    cancel: function () {

    },

    // Optional. "preview" (default) is a preview link to the document for sharing,
    // "direct" is an expiring link to download the contents of the file. For more
    // information about link types, see Link types below.
    linkType: "direct", // or "direct"

    // Optional. A value of false (default) limits selection to a single file, while
    // true enables multiple file selection.
    multiselect: false, // or true

    // Optional. This is a list of file extensions. If specified, the user will
    // only be able to select files with these extensions. You may also specify
    // file types, such as "video" or "images" in the list. For more information,
    // see File types below. By default, all extensions are allowed.
    extensions: ['.csv'],

    // Optional. A value of false (default) limits selection to files,
    // while true allows the user to select both folders and files.
    // You cannot specify `linkType: "direct"` when using `folderselect: true`.
    folderselect: false, // or true
};

function dropboxFiles() {
    Dropbox.choose(options);
}

function dropboxCSV() {
    Dropbox.choose(optionsCSV);
}