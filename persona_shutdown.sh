#!/bin/bash

echo "Shutting down Persona services..."
systemctl --user stop persona.target
echo "Persona services stopped."
