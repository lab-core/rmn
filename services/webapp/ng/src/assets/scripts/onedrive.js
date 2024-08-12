
function onedrivePicker() {
    var odOptions = {
        clientId: "a8a397a1-6d6f-4930-9cb0-9a07b56a92ba",
        action: "download",
        multiSelect: false,
        openInNewWindow: true,
        advanced: {
            redirectUri: "https://132.207.12.29/new-correction",
            // redirectUri: "http://localhost:4200/new-correction",
            filter: ".pdf,.zip"
        },
        success: function (files) {
            document.getElementById("files-onedrive-input").setAttribute("value", files['value'][0]['@microsoft.graph.downloadUrl'])
            document.getElementById("files-upload-label").setAttribute("value", files['value'][0]['name'])
            document.getElementById("files-upload-label").innerHTML = files['value'][0]['name']
            document.getElementById("number-page-container").style.display = (files['value'][0]['name'].endsWith('.zip')) ? 'none' : 'block'
        },
        cancel: function () { },
        error: function (error) {
            console.error(error);
        },
    };
    OneDrive.open(odOptions);
}


function onedrivePickerCSV() {
    var odOptions = {
        clientId: "a8a397a1-6d6f-4930-9cb0-9a07b56a92ba",
        action: "download",
        multiSelect: false,
        openInNewWindow: true,
        advanced: {
            redirectUri: "http://localhost:4200/new-correction",
            filter: ".csv"
        },
        success: function (files) {
            document.getElementById("csv-onedrive-input").setAttribute("value", files['value'][0]['@microsoft.graph.downloadUrl'])
            document.getElementById("csv-upload-label").setAttribute("value", files['value'][0]['name'])
            document.getElementById("csv-upload-label").innerHTML = files['value'][0]['name']
        },
        cancel: function () { },
        error: function (error) {
            console.error(error);
        },
    };
    OneDrive.open(odOptions);
}
