"""Generate/check the composed platform + both domain OpenAPI without production data."""
import argparse,tempfile,json
from pathlib import Path
from tomo.app import create_product_app
from tomo.platform.config import Settings


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='tomo-contract-') as directory:
        app=create_product_app(Settings(database=str(Path(directory)/'qa.sqlite3')))
        generated=json.dumps(app.openapi(),ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    path=Path(__file__).resolve().parents[1]/'docs/contracts/product-openapi.json'
    if args.check:
        if path.read_text()!=generated:raise SystemExit('Composed OpenAPI drift; regenerate and review')
        print('Product OpenAPI matches both implemented domains and platform')
    else:path.write_text(generated);print('Product OpenAPI generated')
if __name__=='__main__':main()
