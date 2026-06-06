// Search Functionality
document.getElementById('searchInput').addEventListener('keyup', function() {
    let filter = this.value.toUpperCase();
    let rows = document.querySelector("#employeeList").rows;

    for (let i = 0; i < rows.length; i++) {
        let firstCol = rows[i].cells[0].textContent.toUpperCase();
        let secondCol = rows[i].cells[1].textContent.toUpperCase();
        if (firstCol.indexOf(filter) > -1 || secondCol.indexOf(filter) > -1) {
            rows[i].style.display = "";
        } else {
            rows[i].style.display = "none";
        }      
    }
});

function viewEmp(id) {
    alert("Viewing Employee ID: " + id);
    // Dito natin ilalagay yung AJAX call mamaya
}