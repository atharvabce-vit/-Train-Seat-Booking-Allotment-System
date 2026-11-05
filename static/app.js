document.addEventListener('DOMContentLoaded', function () {
    initTravelDates();
    initStationAutocomplete();
    initPassengerRows();
    initSeatMap();
});

function initSeatMap() {
    var node = document.getElementById('seatmap');
    if (!node) {
        return;
    }
    var params = new URLSearchParams({
        train_id: node.dataset.train,
        cls: node.dataset.cls,
        date: node.dataset.date,
        from_seq: node.dataset.from,
        to_seq: node.dataset.to,
        quota: node.dataset.quota
    });

    fetch('/api/seatmap?' + params.toString())
        .then(function (response) { return response.json(); })
        .then(function (data) {
            node.innerHTML = '';
            var coaches = data.coaches || [];
            if (!coaches.length) {
                node.innerHTML = '<p class="muted">No seats to display.</p>';
                return;
            }
            coaches.forEach(function (coach) {
                var box = document.createElement('div');
                box.className = 'coach';
                var title = document.createElement('h4');
                title.textContent = coach.name;
                box.appendChild(title);
                var grid = document.createElement('div');
                grid.className = 'seat-grid';
                coach.seats.forEach(function (seat) {
                    var cell = document.createElement('span');
                    cell.className = 'seat seat-' + seat.status;
                    cell.title = seat.berth_type;
                    cell.textContent = seat.seat_number;
                    grid.appendChild(cell);
                });
                box.appendChild(grid);
                node.appendChild(box);
            });
        })
        .catch(function () {
            node.innerHTML = '<p class="muted">Seat map unavailable right now.</p>';
        });
}

function initTravelDates() {
    var today = new Date();
    var max = new Date();
    max.setDate(today.getDate() + 30);
    var min = today.toISOString().slice(0, 10);
    var limit = max.toISOString().slice(0, 10);
    document.querySelectorAll('input[data-travel-date]').forEach(function (input) {
        input.min = min;
        input.max = limit;
        if (!input.value) {
            input.value = limit;
        }
    });
}

function initStationAutocomplete() {
    var inputs = document.querySelectorAll('input[data-stations]');
    if (!inputs.length) {
        return;
    }
    var list = document.createElement('datalist');
    list.id = 'station-list';
    document.body.appendChild(list);
    inputs.forEach(function (input) {
        input.setAttribute('list', 'station-list');
    });

    fetch('/api/stations?q=')
        .then(function (response) { return response.json(); })
        .then(function (data) {
            (data.stations || []).forEach(function (station) {
                var option = document.createElement('option');
                option.value = station.city;
                option.label = station.name + ' (' + station.code + ')';
                list.appendChild(option);
            });
        })
        .catch(function () {});
}

function initPassengerRows() {
    var body = document.getElementById('passenger-rows');
    var template = document.getElementById('passenger-row-template');
    var addButton = document.getElementById('add-passenger');
    if (!body || !template || !addButton) {
        return;
    }

    function updateFare() {
        var selected = document.querySelector('input[name="class_code"]:checked');
        var total = document.getElementById('fare-total');
        if (!selected || !total) {
            return;
        }
        var count = body.querySelectorAll('tr').length;
        var fare = parseInt(selected.dataset.fare, 10) || 0;
        total.textContent = 'Rs ' + (fare * count);
    }

    function addRow() {
        if (body.querySelectorAll('tr').length >= 6) {
            return;
        }
        var row = template.content.firstElementChild.cloneNode(true);
        row.querySelector('.remove-row').addEventListener('click', function () {
            row.remove();
            updateFare();
        });
        body.appendChild(row);
        updateFare();
    }

    addButton.addEventListener('click', addRow);
    document.querySelectorAll('input[name="class_code"]').forEach(function (radio) {
        radio.addEventListener('change', updateFare);
    });
    addRow();
    addRow();
}
