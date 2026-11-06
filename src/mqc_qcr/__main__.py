import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="Local MQC OCR / rule / scoring demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="runtime")
    args = parser.parse_args()
    os.environ["MQC_DATA_DIR"] = os.path.abspath(args.data_dir)
    import uvicorn
    uvicorn.run("mqc_qcr.app:app", host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
