import { useState } from "react";


function App() {

  const [note, setNote] = useState(
    "Do not charge battery between 2 PM and 4 PM"
  );

  const [result, setResult] = useState(null);

  const [loading, setLoading] = useState(false);


  async function optimize() {

    setLoading(true);

    try {

      const res = await fetch(
        "http://127.0.0.1:8000/optimize-energy",
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json"
          },

          body: JSON.stringify({

            operator_note: note,

            demand: Array(24).fill(100),

            solar: Array(24).fill(50),

            tariff: Array(24).fill(10),

            battery: {
              capacity: 200,
              initial: 100,
              max_charge: 50,
              max_discharge: 50
            }

          })
        }
      );


      const data = await res.json();

      setResult(data);


    } catch(err) {

      console.log(err);

      alert("API connection failed");

    }


    setLoading(false);

  }



  return (

    <div style={{
      background:"#111",
      color:"white",
      minHeight:"100vh",
      padding:"40px"
    }}>


      <h1>
        GridWise Copilot
      </h1>


      <h2>
        Operator Instruction
      </h2>


      <textarea

        value={note}

        onChange={
          e=>setNote(e.target.value)
        }

        rows="5"

        cols="60"

      />


      <br/>


      <button
        onClick={optimize}
        disabled={loading}
      >

        {
          loading
          ?
          "Optimizing..."
          :
          "Optimize Energy"
        }

      </button>



      {
        result &&

        <div>

          <h2>
            Optimization Result
          </h2>


          <p>
            Status: {result.status}
          </p>


          <p>
            Cost: {result.total_cost_bdt} BDT
          </p>


          <h3>
            Battery Summary
          </h3>


          <pre>
            {
              JSON.stringify(
                result.battery_summary,
                null,
                2
              )
            }
          </pre>


          <h3>
            Hourly Plan
          </h3>


          <table border="1">

            <thead>
              <tr>
                <th>Hour</th>
                <th>Grid</th>
                <th>Solar</th>
                <th>Battery</th>
              </tr>
            </thead>


            <tbody>

            {
              result.hourly_plan.map(
                item=>(

                  <tr key={item.hour}>

                    <td>
                      {item.hour}
                    </td>

                    <td>
                      {item.grid_kwh}
                    </td>

                    <td>
                      {item.solar_kwh}
                    </td>

                    <td>
                      {item.battery_kwh}
                    </td>

                  </tr>

                )
              )
            }

            </tbody>

          </table>


        </div>

      }


    </div>

  );

}


export default App;