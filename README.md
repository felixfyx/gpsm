# General Purpose Serial Messenger (GPSM)
An attempt at creating a general purpose serial message handler for communicating between the PC and Microcontroller units like Arduino

## General packet structure
A typical packet structure is defined like so:

<table>
<tr>
<td> Start Byte </td>
<td> Length </td>
<td> Command ID </td>
<td> Variable Length Data Payload </td>
<td> Checksum </td>
</tr>
</table>

Do note that that the `variable length data payload` can be empty